using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace HearthLauncher;

public enum SteamLaunchKind { Native, Flatpak }
public sealed record LaunchPlan(string Executable, IReadOnlyList<string> Arguments);

public static class PlatformIntegration
{
    public const string ProtonLaunchOptions = "WINEDLLOVERRIDES=\"winhttp=n,b\" %command%";
    static readonly StringComparer PathComparer = OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;
    static readonly Regex DnsLabel = new(@"\A[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\z", RegexOptions.CultureInvariant);

    public static string DefaultStateDirectory => OperatingSystem.IsWindows()
        ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "HearthLauncher")
        : Path.Combine(AbsoluteEnvironment("XDG_STATE_HOME") ?? Path.Combine(HomeDirectory(), ".local", "state"), "HearthLauncher");

    static string HomeDirectory()
    {
        string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        if (!Path.IsPathFullyQualified(home)) throw new IOException("Не найдена домашняя папка пользователя.");
        return home;
    }
    static string? AbsoluteEnvironment(string name)
    {
        string? value = Environment.GetEnvironmentVariable(name);
        return !string.IsNullOrEmpty(value) && Path.IsPathFullyQualified(value) ? value : null;
    }
    static void SupportedPlatform()
    {
        if (!OperatingSystem.IsWindows() && !OperatingSystem.IsLinux())
            throw new PlatformNotSupportedException("Поддерживаются Windows и Linux с Proton.");
    }

    public static string NormalizeAddress(string address)
    {
        if (address is null || address.Length > 260 || address.Any(c => char.IsWhiteSpace(c) || char.IsControl(c)))
            throw new InvalidDataException("Укажите адрес сервера в формате host:port или [IPv6]:port.");
        if (address.Length == 0) return "";
        string host, portText;
        bool ipv6 = address[0] == '[';
        if (ipv6)
        {
            int closing = address.IndexOf(']');
            if (closing < 2 || closing + 1 >= address.Length || address[closing + 1] != ':') throw BadAddress();
            host = address[1..closing]; portText = address[(closing + 2)..];
            if (host.Contains('%') || !IPAddress.TryParse(host, out var ip) || ip.AddressFamily != AddressFamily.InterNetworkV6) throw BadAddress();
            host = ip.ToString();
        }
        else
        {
            int colon = address.LastIndexOf(':');
            if (colon <= 0 || address[..colon].Contains(':')) throw BadAddress();
            host = address[..colon]; portText = address[(colon + 1)..];
            if (host.All(c => c is >= '0' and <= '9' || c == '.'))
            {
                // IPAddress.TryParse also accepts abbreviated, octal and integer IPv4. Do not accept those as DNS.
                string[] parts = host.Split('.');
                if (parts.Length != 4 || parts.Any(p => p.Length is < 1 or > 3 || (p.Length > 1 && p[0] == '0')
                    || !byte.TryParse(p, NumberStyles.None, CultureInfo.InvariantCulture, out _))) throw BadAddress();
            }
            else if (host.Length > 253 || host.Split('.').Any(label => !DnsLabel.IsMatch(label))) throw BadAddress();
            host = host.ToLowerInvariant();
        }
        if (portText.Length is < 1 or > 5 || portText.Any(c => c is < '0' or > '9')
            || !int.TryParse(portText, NumberStyles.None, CultureInfo.InvariantCulture, out int port) || port is < 1 or > 65535) throw BadAddress();
        return (ipv6 ? "[" + host + "]" : host) + ":" + port.ToString(CultureInfo.InvariantCulture);
    }
    static InvalidDataException BadAddress() => new("Укажите адрес сервера в формате host:port или [IPv6]:port, порт от 1 до 65535.");

    // Pure plan: no shell expansion, no passwords, no environment changes to a running Steam client.
    // Doorstop 3: --doorstop-enable; Doorstop 4.4.0 in the pinned V+ archive: --doorstop-enabled.
    public static LaunchPlan BuildLaunchPlan(string steamExecutable, string address, bool vanilla,
        int? doorstopMajor = null, SteamLaunchKind kind = SteamLaunchKind.Native)
    {
        if (string.IsNullOrWhiteSpace(steamExecutable) || steamExecutable.Any(char.IsControl)) throw new InvalidDataException("Не найден Steam.");
        address = NormalizeAddress(address);
        var arguments = new List<string>();
        if (kind == SteamLaunchKind.Flatpak) arguments.AddRange(["run", "com.valvesoftware.Steam"]);
        else if (kind != SteamLaunchKind.Native) throw new InvalidDataException("Неизвестный способ запуска Steam.");
        arguments.AddRange(["-applaunch", "892970"]);
        if (address.Length != 0) arguments.AddRange(["+connect", address]);
        if (vanilla && doorstopMajor is not null)
        {
            string option = doorstopMajor switch { 3 => "--doorstop-enable", 4 => "--doorstop-enabled", _ => throw new InvalidDataException("Неизвестный загрузчик модов: безопасный запуск без модов недоступен.") };
            arguments.AddRange([option, "false"]);
        }
        return new(steamExecutable, arguments.AsReadOnly());
    }

    public static List<string> LinuxSteamRoots(string home, string? xdgDataHome = null)
    {
        if (!Path.IsPathFullyQualified(home)) throw new InvalidDataException("Нужен абсолютный путь домашней папки.");
        var roots = new List<string> { Path.Combine(home, ".steam", "steam"), Path.Combine(home, ".steam", "root"),
            Path.Combine(home, ".local", "share", "Steam"),
            Path.Combine(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam"),
            Path.Combine(home, "snap", "steam", "common", ".local", "share", "Steam") };
        if (!string.IsNullOrEmpty(xdgDataHome) && Path.IsPathFullyQualified(xdgDataHome)) roots.Add(Path.Combine(xdgDataHome, "Steam"));
        return roots;
    }
    static List<string> WindowsSteamRoots()
    {
        var roots = new List<string>();
        if (!OperatingSystem.IsWindows()) return roots;
        foreach (var hive in new[] { RegistryHive.CurrentUser, RegistryHive.LocalMachine })
        foreach (var view in new[] { RegistryView.Registry32, RegistryView.Registry64 })
        {
            try
            {
                using var registry = RegistryKey.OpenBaseKey(hive, view);
                using var key = registry.OpenSubKey(@"Software\Valve\Steam");
                foreach (string name in new[] { "SteamPath", "InstallPath" })
                    if (key?.GetValue(name) is string value && Path.IsPathFullyQualified(value)) roots.Add(value);
            }
            catch (Exception error) when (error is System.Security.SecurityException or UnauthorizedAccessException or IOException) { }
        }
        foreach (var folder in new[] { Environment.SpecialFolder.ProgramFilesX86, Environment.SpecialFolder.ProgramFiles })
        {
            string path = Environment.GetFolderPath(folder);
            if (Path.IsPathFullyQualified(path)) roots.Add(Path.Combine(path, "Steam"));
        }
        return roots.Distinct(PathComparer).ToList();
    }
    public static List<string> FindGames()
    {
        SupportedPlatform();
        return FindGamesInRoots(OperatingSystem.IsWindows() ? WindowsSteamRoots() : LinuxSteamRoots(HomeDirectory(), AbsoluteEnvironment("XDG_DATA_HOME")));
    }
    public static List<string> FindGamesInRoots(IEnumerable<string> roots)
    {
        var libraries = new HashSet<string>(PathComparer);
        foreach (string root in roots)
        {
            try { foreach (string library in LibrariesForRoot(root)) libraries.Add(library); }
            catch (Exception error) when (DiscoveryError(error)) { }
        }
        var games = new HashSet<string>(PathComparer);
        foreach (string library in libraries)
        {
            try { if (GameInLibrary(library) is string game) games.Add(game); }
            catch (Exception error) when (DiscoveryError(error)) { }
        }
        return games.OrderBy(p => p, PathComparer).ToList();
    }
    static bool DiscoveryError(Exception error) => error is IOException or InvalidDataException or UnauthorizedAccessException or ArgumentException or NotSupportedException;
    static List<string> LibrariesForRoot(string root)
    {
        root = CanonicalDirectory(root);
        var libraries = new List<string> { root };
        string file = Path.Combine(root, "steamapps", "libraryfolders.vdf");
        if (!File.Exists(file)) return libraries;
        // A bad optional library list must not hide the root's own installation.
        try
        {
            var map = ParseVdf(ReadBounded(file));
            if (map.TryGetValue("libraryfolders", out var value) && value is Dictionary<string, object> folders)
            foreach (var entry in folders.Where(e => e.Key.Length != 0 && e.Key.All(c => c is >= '0' and <= '9')))
            {
                string? path = entry.Value as string;
                if (entry.Value is Dictionary<string, object> folder && folder.TryGetValue("path", out var p)) path = p as string;
                if (path is not null && Path.IsPathFullyQualified(path))
                {
                    try { libraries.Add(CanonicalDirectory(path)); } catch (Exception error) when (DiscoveryError(error)) { }
                }
            }
        }
        catch (Exception error) when (DiscoveryError(error)) { }
        return libraries;
    }
    static string? GameInLibrary(string library)
    {
        string manifest = Path.Combine(library, "steamapps", "appmanifest_892970.acf");
        if (!File.Exists(manifest)) return null;
        var map = ParseVdf(ReadBounded(manifest));
        if (!map.TryGetValue("AppState", out var state) || state is not Dictionary<string, object> app
            || !app.TryGetValue("appid", out var appId) || appId is not string id || id != "892970"
            || !app.TryGetValue("installdir", out var directory) || directory is not string name
            || name.Length is < 1 or > 255 || name is "." or ".." || name.Any(char.IsControl) || name.IndexOfAny(['/', '\\', ':']) >= 0) return null;
        string path = Path.Combine(library, "steamapps", "common", name);
        return File.Exists(Path.Combine(path, "valheim.exe")) && Directory.Exists(Path.Combine(path, "valheim_Data")) ? CanonicalDirectory(path) : null;
    }
    static string ReadBounded(string file)
    {
        using var stream = File.OpenRead(file);
        if (stream.Length > 2 * 1024 * 1024) throw new InvalidDataException("Слишком большой файл Steam.");
        using var reader = new StreamReader(stream, Encoding.UTF8, true);
        char[] data = new char[2 * 1024 * 1024 + 1];
        int count = reader.ReadBlock(data, 0, data.Length);
        if (count == data.Length) throw new InvalidDataException("Слишком большой файл Steam.");
        return new string(data, 0, count);
    }
    public static string CanonicalDirectory(string path)
    {
        if (!Path.IsPathFullyQualified(path)) throw new InvalidDataException("Нужен абсолютный путь папки.");
        string full = Path.GetFullPath(path), current = Path.GetPathRoot(full)!;
        foreach (string part in full[current.Length..].Split([Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar], StringSplitOptions.RemoveEmptyEntries))
        {
            var directory = new DirectoryInfo(Path.Combine(current, part));
            if (!directory.Exists) throw new DirectoryNotFoundException("Папка не найдена: " + path);
            current = (directory.Attributes & FileAttributes.ReparsePoint) != 0
                ? (directory.ResolveLinkTarget(true) ?? throw new IOException("Не удалось разрешить папку-ссылку.")).FullName : directory.FullName;
        }
        return Path.TrimEndingDirectorySeparator(current);
    }
    public static Dictionary<string, object> ParseVdf(string text)
    {
        if (text.Length > 2 * 1024 * 1024) throw new InvalidDataException("Слишком большой файл Steam.");
        var tokens = new List<string>();
        for (int i = 0; i < text.Length;)
        {
            if (char.IsWhiteSpace(text[i]) || text[i] == '\ufeff') { i++; continue; }
            if (text[i] == '/' && i + 1 < text.Length && text[i + 1] == '/') { while (i < text.Length && text[i] != '\n') i++; continue; }
            if (text[i] is '{' or '}') { tokens.Add(text[i++].ToString()); continue; }
            var word = new StringBuilder();
            if (text[i] == '"')
            {
                i++; bool closed = false;
                while (i < text.Length)
                {
                    char c = text[i++]; if (c == '"') { closed = true; break; }
                    if (c == '\\' && i < text.Length && text[i] is '\\' or '"') c = text[i++];
                    word.Append(c);
                }
                if (!closed) throw new InvalidDataException("Повреждён файл Steam.");
            }
            else while (i < text.Length && !char.IsWhiteSpace(text[i]) && text[i] is not ('{' or '}')) word.Append(text[i++]);
            tokens.Add(word.ToString());
        }
        int position = 0;
        Dictionary<string, object> Read(bool nested, int depth)
        {
            if (depth > 32) throw new InvalidDataException("Слишком глубокий файл Steam.");
            var result = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            while (position < tokens.Count)
            {
                string key = tokens[position++];
                if (key == "}") { if (!nested) throw new InvalidDataException("Некорректный VDF."); return result; }
                if (key == "{" || position >= tokens.Count) throw new InvalidDataException("Некорректный VDF.");
                string value = tokens[position++];
                if (value == "}") throw new InvalidDataException("Некорректный VDF.");
                result[key] = value == "{" ? Read(true, depth + 1) : value;
            }
            if (nested) throw new InvalidDataException("Незакрытый VDF.");
            return result;
        }
        return Read(false, 0);
    }

    public static void EnsureGameClosed()
    {
        SupportedPlatform();
        if (OperatingSystem.IsLinux())
        {
            if (geteuid() == 0) throw new IOException("Запустите лаунчер от своего пользователя, без sudo.");
            EnsureGameClosedFromProc("/proc");
            return;
        }
        Process[] processes;
        try { processes = Process.GetProcesses(); }
        catch (Exception error) { throw new IOException("Не удалось проверить, закрыта ли Valheim.", error); }
        try
        {
            foreach (var process in processes)
            {
                try { EnsureNamesClosed([process.ProcessName]); }
                catch (InvalidOperationException) { if (!process.HasExited) throw; }
                catch (Win32Exception error) { throw new IOException("Не удалось проверить, закрыта ли Valheim.", error); }
            }
        }
        finally { foreach (var process in processes) process.Dispose(); }
    }
    internal static void EnsureNamesClosed(IEnumerable<string> names)
    {
        foreach (string name in names)
            if (name.Equals("valheim", StringComparison.OrdinalIgnoreCase) || name.Equals("valheim.exe", StringComparison.OrdinalIgnoreCase)
                || name.Equals("valheim.x86_64", StringComparison.OrdinalIgnoreCase)) throw new IOException("Закройте Valheim перед установкой, восстановлением или запуском.");
    }
    internal static void EnsureGameClosedFromProc(string procDirectory)
    {
        try
        {
            foreach (string process in Directory.EnumerateDirectories(procDirectory))
            {
                string id = Path.GetFileName(process);
                if (id.Length == 0 || !id.All(c => c is >= '0' and <= '9')) continue;
                try
                {
                    using var input = new StreamReader(File.OpenRead(Path.Combine(process, "comm")), Encoding.UTF8, true, 128);
                    char[] name = new char[128]; int count = input.ReadBlock(name, 0, name.Length);
                    if (count == name.Length) throw new IOException("Не удалось прочитать имя процесса.");
                    EnsureNamesClosed([new string(name, 0, count).TrimEnd('\n', '\r')]);
                }
                catch (FileNotFoundException) { if (Directory.Exists(process)) throw; }
                catch (DirectoryNotFoundException) { if (Directory.Exists(process)) throw; }
            }
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        { throw new IOException("Закройте Valheim; если проверка процессов недоступна, запуск и изменение файлов запрещены.", error); }
    }
    [DllImport("libc")] static extern uint geteuid();

    internal static int? DoorstopMajor(string gameDirectory)
    {
        string file = Path.Combine(gameDirectory, "winhttp.dll");
        if (new FileInfo(file).LinkTarget is not null) throw new IOException("Загрузчик модов не должен быть ссылкой.");
        if (!File.Exists(file)) return null;
        if ((File.GetAttributes(file) & FileAttributes.ReparsePoint) != 0) throw new IOException("Загрузчик модов не должен быть ссылкой.");
        using var stream = File.OpenRead(file);
        if (stream.Length is < 2 or > 16 * 1024 * 1024) throw new IOException("Неизвестный загрузчик модов: безопасный запуск без модов недоступен.");
        byte[] bytes = new byte[(int)stream.Length]; stream.ReadExactly(bytes);
        if (bytes[0] != 'M' || bytes[1] != 'Z') throw new IOException("Неизвестный загрузчик модов: безопасный запуск без модов недоступен.");
        bool Has(string value) => bytes.AsSpan().IndexOf(Encoding.Unicode.GetBytes(value + "\0")) >= 0
            || bytes.AsSpan().IndexOf(Encoding.ASCII.GetBytes(value + "\0")) >= 0;
        if (Has("--doorstop-enabled")) return 4;
        if (Has("--doorstop-enable")) return 3;
        throw new IOException("Неизвестный загрузчик модов: безопасный запуск без модов недоступен.");
    }
    internal static SteamLaunchKind SteamKindForRoot(string root) => CanonicalDirectory(root)
        .Contains(Path.Combine(".var", "app", "com.valvesoftware.Steam") + Path.DirectorySeparatorChar, StringComparison.Ordinal)
        ? SteamLaunchKind.Flatpak : SteamLaunchKind.Native;
    internal static string SteamRootForGame(IEnumerable<string> roots, string gameDirectory)
    {
        string game = CanonicalDirectory(gameDirectory);
        foreach (string root in roots)
        {
            var games = FindGamesInRoots([root]);
            if (!games.Any(p => PathComparer.Equals(p, game))) continue;
            // -applaunch selects the AppID, never a supplied directory. Refuse an ambiguous installation.
            if (games.Count != 1) throw new IOException("В библиотеках Steam найдены несколько копий Valheim. Оставьте нужную установку в Steam: запуск по AppID не позволяет выбрать папку.");
            return root;
        }
        throw new IOException("Выбранная папка не найдена в библиотеке Steam. Укажите установленную Steam-копию Valheim.");
    }
    public static void LaunchGame(string gameDirectory, string address, bool vanilla, Action<string> log)
    {
        SupportedPlatform(); NormalizeAddress(address); EnsureGameClosed();
        string game = CanonicalDirectory(gameDirectory);
        if (!File.Exists(Path.Combine(game, "valheim.exe")) || !Directory.Exists(Path.Combine(game, "valheim_Data"))) throw new IOException("Выберите папку Windows-версии Valheim из Steam.");
        var roots = OperatingSystem.IsWindows() ? WindowsSteamRoots() : LinuxSteamRoots(HomeDirectory(), AbsoluteEnvironment("XDG_DATA_HOME"));
        string matching = SteamRootForGame(roots, game);
        string executable; var kind = SteamLaunchKind.Native;
        if (OperatingSystem.IsWindows()) executable = Path.Combine(matching, "Steam.exe");
        else if (SteamKindForRoot(matching) == SteamLaunchKind.Flatpak)
        { executable = SystemExecutable("flatpak"); kind = SteamLaunchKind.Flatpak; }
        else if (CanonicalDirectory(matching).Contains(Path.Combine("snap", "steam") + Path.DirectorySeparatorChar, StringComparison.Ordinal)) executable = "/snap/bin/steam";
        else executable = SystemExecutable("steam");
        if (!File.Exists(executable)) throw new IOException("Не найден Steam. Установите или откройте Steam и повторите.");
        var plan = BuildLaunchPlan(executable, address, vanilla, vanilla ? DoorstopMajor(game) : null, kind);
        if (OperatingSystem.IsLinux()) log("Для Proton настройте Valheim → Свойства → Совместимость и параметры запуска: " + ProtonLaunchOptions + ". Сохраните другие опции; %command% должен встречаться один раз. Настройки Steam автоматически не меняются.");
        EnsureGameClosed();
        using var process = Process.Start(ToStartInfo(plan)) ?? throw new IOException("Не удалось отправить команду запуска Steam.");
        log("Команда запуска отправлена Steam. Дождитесь запуска Valheim; вход в аккаунт и обновление игры выполняет Steam.");
    }
    static string SystemExecutable(string name)
    {
        foreach (string directory in new[] { "/usr/bin", "/usr/games", "/bin" })
        { string path = Path.Combine(directory, name); if (File.Exists(path)) return path; }
        throw new IOException("Не найден " + name + ". Установите его через менеджер пакетов системы.");
    }
    public static ProcessStartInfo ToStartInfo(LaunchPlan plan)
    {
        var start = new ProcessStartInfo(plan.Executable) { UseShellExecute = false };
        foreach (string argument in plan.Arguments) start.ArgumentList.Add(argument);
        return start;
    }
    public static string NormalizeWebUrl(string url)
    {
        if (url is null || url.Length > 4096 || url.Any(c => char.IsControl(c) || char.IsWhiteSpace(c)) || url.Contains('\\')
            || !Uri.TryCreate(url, UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https") || uri.Host.Length == 0 || uri.UserInfo.Length != 0)
            throw new InvalidDataException("Разрешены только адреса HTTP или HTTPS без пароля.");
        return uri.AbsoluteUri;
    }
    public static void OpenUrl(string url)
    {
        SupportedPlatform(); url = NormalizeWebUrl(url);
        var start = OperatingSystem.IsWindows() ? new ProcessStartInfo(url) { UseShellExecute = true }
            : ToStartInfo(new(SystemExecutable("xdg-open"), new[] { url }));
        using var process = Process.Start(start) ?? throw new IOException("Не удалось открыть браузер.");
    }
}
