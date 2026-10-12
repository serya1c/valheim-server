using System.Text;

namespace HearthLauncher.Tests;

public static class PlatformTests
{
    static int assertions;
    static void Check(bool value, string description)
    {
        assertions++;
        if (!value) throw new Exception("Platform: " + description);
    }
    static void Reject(Action action, string description)
    {
        assertions++;
        try { action(); }
        catch (Exception error) when (error is IOException or InvalidDataException or ArgumentException) { return; }
        throw new Exception("Platform accepted: " + description);
    }
    static string VdfString(string value) => "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    static string GameFixture(string library, string name = "Valheim")
    {
        string game = Path.Combine(library, "steamapps", "common", name);
        Directory.CreateDirectory(Path.Combine(game, "valheim_Data"));
        File.WriteAllText(Path.Combine(game, "valheim.exe"), "fixture: never execute");
        File.WriteAllText(Path.Combine(library, "steamapps", "appmanifest_892970.acf"),
            "\ufeff// Fixture only\n\"AppState\" { \"appid\" \"892970\" \"installdir\" " + VdfString(name) + " }");
        return game;
    }
    public static Task RunAsync()
    {
        assertions = 0;
        var accepted = new Dictionary<string, string>
        {
            [""] = "", ["LOKI.ach-play.ru:2456"] = "loki.ach-play.ru:2456", ["localhost:1"] = "localhost:1",
            ["192.168.1.2:65535"] = "192.168.1.2:65535", ["[2001:DB8::1]:2456"] = "[2001:db8::1]:2456",
            ["[::1]:00080"] = "[::1]:80", ["steam-server.example:2457"] = "steam-server.example:2457"
        };
        foreach (var pair in accepted) Check(PlatformIntegration.NormalizeAddress(pair.Key) == pair.Value, "valid endpoint " + pair.Key);
        foreach (string value in new[] { "host", "host:0", "host:65536", "host:-1", "host:+2", "host: 2", "host:2 +password secret",
            "host:2\n--doorstop-enabled true", "host:2\0", "https://host:2", "user@host:2", "host:2/", "host:2?x=1", "host:2#x",
            "a;touch:2", "$(touch):2", "host%20x:2", "'host':2", "host\\foo:2", "-host:2", "host-:2", "a..b:2", "[::1%eth0]:2",
            "::1:2", "[127.0.0.1]:2", "[::1]:2:x", "[::1]:2]", "999.1.1.1:2", "127.1:2", "2130706433:2", "0177.0.0.1:2" })
            Reject(() => PlatformIntegration.NormalizeAddress(value), "unsafe endpoint");

        var native = PlatformIntegration.BuildLaunchPlan("C:/Steam Folder/Steam.exe", "example.org:2456", false);
        Check(native.Executable == "C:/Steam Folder/Steam.exe" && native.Arguments.SequenceEqual(new[] { "-applaunch", "892970", "+connect", "example.org:2456" }), "native plan preserves executable and argument boundaries");
        var start = PlatformIntegration.ToStartInfo(native);
        Check(!start.UseShellExecute && start.Arguments == "" && start.ArgumentList.SequenceEqual(native.Arguments), "launch uses ArgumentList without command string or shell");
        Check(!start.Environment.ContainsKey("WINEDLLOVERRIDES") || start.Environment["WINEDLLOVERRIDES"] == Environment.GetEnvironmentVariable("WINEDLLOVERRIDES"), "launch does not pretend to update running Steam's environment");
        Check(PlatformIntegration.BuildLaunchPlan("steam", "", false).Arguments.SequenceEqual(new[] { "-applaunch", "892970" }), "launch without server supplies no connect argument");
        Check(PlatformIntegration.BuildLaunchPlan("steam", "", true, 3).Arguments.TakeLast(2).SequenceEqual(new[] { "--doorstop-enable", "false" }), "Doorstop 3 disable CLI");
        Check(PlatformIntegration.BuildLaunchPlan("steam", "", true, 4).Arguments.TakeLast(2).SequenceEqual(new[] { "--doorstop-enabled", "false" }), "Doorstop 4 disable CLI");
        Check(PlatformIntegration.BuildLaunchPlan("steam", "", true).Arguments.Count == 2, "clean vanilla copy needs no loader option");
        Reject(() => PlatformIntegration.BuildLaunchPlan("steam", "", true, 5), "unknown loader cannot claim vanilla");
        var flatpak = PlatformIntegration.BuildLaunchPlan("/usr/bin/flatpak", "[::1]:2456", true, 4, SteamLaunchKind.Flatpak);
        Check(flatpak.Arguments.SequenceEqual(new[] { "run", "com.valvesoftware.Steam", "-applaunch", "892970", "+connect", "[::1]:2456", "--doorstop-enabled", "false" }), "Flatpak Steam passes exact arguments to app");
        Reject(() => PlatformIntegration.BuildLaunchPlan("steam", "host:2456 -quit", true, 4), "launch cannot add arguments via endpoint");

        Check(PlatformIntegration.NormalizeWebUrl("https://example.org/path?q=1#section") == "https://example.org/path?q=1#section", "HTTP browser URL remains intact");
        foreach (string value in new[] { "steam://run/892970", "file:///tmp/a", "javascript:alert(1)", "https://user:secret@example.org", "https://example.org\n-x", "https://example.org\\x", "https://example.org x", "--help" })
            Reject(() => PlatformIntegration.NormalizeWebUrl(value), "non-web or ambiguous URL");
        foreach (string name in new[] { "valheim", "valheim.exe", "VALHEIM.EXE", "valheim.x86_64" })
            Reject(() => PlatformIntegration.EnsureNamesClosed(new[] { "steam", name }), "running Valheim process");
        PlatformIntegration.EnsureNamesClosed(new[] { "steam", "valheim_server", "valheim_server.exe", "notvalheim" });
        Check(true, "dedicated server and unrelated processes do not block client installation");

        string fixture = Path.Combine(Path.GetTempPath(), "hearth-platform-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(fixture);
        try
        {
            string home = Path.Combine(fixture, "home"); Directory.CreateDirectory(home);
            var roots = PlatformIntegration.LinuxSteamRoots(home, Path.Combine(fixture, "xdg"));
            Check(roots.Count == 6 && roots.Any(p => p.Contains("com.valvesoftware.Steam")) && roots.Any(p => p.Contains(Path.Combine("snap", "steam"))), "Linux roots include native aliases, Flatpak, Snap, XDG");
            Check(PlatformIntegration.LinuxSteamRoots(home, "relative").Count == 5, "relative XDG paths cannot redirect discovery");
            string root = roots[2], extra = Path.Combine(fixture, "External library");
            string rootGame = GameFixture(root), extraGame = GameFixture(extra, "Valheim with spaces");
            File.WriteAllText(Path.Combine(root, "steamapps", "libraryfolders.vdf"),
                "\"libraryfolders\" { \"0\" { \"path\" " + VdfString(root) + " \"apps\" { \"892970\" \"1\" } } \"1\" " + VdfString(extra) + " }");
            var games = PlatformIntegration.FindGamesInRoots(new[] { root, root, Path.Combine(fixture, "missing") });
            Check(games.Count == 2 && games.Contains(rootGame) && games.Contains(extraGame), "modern and legacy Steam libraries with spaces deduplicate");
            Reject(() => PlatformIntegration.SteamRootForGame(new[] { root }, extraGame), "AppID launch cannot choose between multiple installed copies in one Steam client");
            File.WriteAllText(Path.Combine(root, "steamapps", "libraryfolders.vdf"), "\"libraryfolders\" { broken");
            Check(PlatformIntegration.FindGamesInRoots(new[] { root, extra }).Count == 2, "broken library list preserves root's installation and independent libraries");
            string wrong = Path.Combine(fixture, "wrong"); GameFixture(wrong);
            string manifest = Path.Combine(wrong, "steamapps", "appmanifest_892970.acf");
            File.WriteAllText(manifest, "AppState { appid 123 installdir Valheim }");
            Check(PlatformIntegration.FindGamesInRoots(new[] { wrong }).Count == 0, "wrong AppID cannot impersonate Valheim");
            foreach (string name in new[] { "", "..", "../Valheim", "Valheim\\..", "C:Valheim" })
            {
                File.WriteAllText(manifest, "AppState { appid 892970 installdir " + VdfString(name) + " }");
                Check(PlatformIntegration.FindGamesInRoots(new[] { wrong }).Count == 0, "unsafe installdir is ignored");
            }
            File.WriteAllText(manifest, "AppState { appid 892970 installdir Valheim }");
            File.Delete(Path.Combine(wrong, "steamapps", "common", "Valheim", "valheim.exe"));
            Check(PlatformIntegration.FindGamesInRoots(new[] { wrong }).Count == 0, "native Linux files are not a Windows Proton game");
            string flatpakRoot = roots[3]; string flatpakGame = GameFixture(flatpakRoot);
            Check(PlatformIntegration.FindGamesInRoots(new[] { flatpakRoot }).Single() == flatpakGame && PlatformIntegration.SteamKindForRoot(flatpakRoot) == SteamLaunchKind.Flatpak, "Flatpak root selects Flatpak Steam");
            Check(PlatformIntegration.SteamRootForGame(new[] { root, flatpakRoot }, flatpakGame) == flatpakRoot, "selected game folder chooses its associated Steam client");
            Reject(() => PlatformIntegration.SteamRootForGame(new[] { root }, extraGame), "folder outside the selected Steam libraries cannot launch a different installation");
            Check(PlatformIntegration.SteamKindForRoot(root) == SteamLaunchKind.Native, "native root selects native Steam");
            if (OperatingSystem.IsLinux())
            {
                string alias = roots[0]; Directory.CreateDirectory(Path.GetDirectoryName(alias)!);
                Directory.CreateSymbolicLink(alias, flatpakRoot);
                Check(PlatformIntegration.CanonicalDirectory(alias) == flatpakRoot, "Steam folder alias canonicalizes on Linux");
                Check(PlatformIntegration.FindGamesInRoots(new[] { alias, flatpakRoot }).Count == 1 && PlatformIntegration.SteamKindForRoot(alias) == SteamLaunchKind.Flatpak, "alias deduplicates and retains Flatpak routing");
            }

            string proc = Path.Combine(fixture, "proc"); Directory.CreateDirectory(Path.Combine(proc, "1"));
            File.WriteAllText(Path.Combine(proc, "1", "comm"), "steam\n");
            PlatformIntegration.EnsureGameClosedFromProc(proc);
            Check(true, "readable proc fixture confirms game closed");
            File.WriteAllText(Path.Combine(proc, "1", "comm"), "valheim.exe\n");
            Reject(() => PlatformIntegration.EnsureGameClosedFromProc(proc), "Proton process blocks writes");
            File.Delete(Path.Combine(proc, "1", "comm"));
            Reject(() => PlatformIntegration.EnsureGameClosedFromProc(proc), "unreadable process state fails closed");
            Reject(() => PlatformIntegration.EnsureGameClosedFromProc(Path.Combine(fixture, "not-proc")), "missing process inventory fails closed");

            string loaderGame = Path.Combine(fixture, "loader"); Directory.CreateDirectory(loaderGame);
            Check(PlatformIntegration.DoorstopMajor(loaderGame) is null, "no loader needs no disabling");
            string loader = Path.Combine(loaderGame, "winhttp.dll"), configuration = Path.Combine(loaderGame, "doorstop_config.ini");
            File.WriteAllText(configuration, "[General]\nenabled = true\n");
            foreach (var pair in new[] { (3, "--doorstop-enable"), (4, "--doorstop-enabled") })
            {
                File.WriteAllBytes(loader, new byte[] { (byte)'M', (byte)'Z' }.Concat(Encoding.Unicode.GetBytes("\0" + pair.Item2 + "\0")).ToArray());
                Check(PlatformIntegration.DoorstopMajor(loaderGame) == pair.Item1, "loader capability identifies actual CLI generation");
            }
            File.WriteAllText(Path.Combine(loaderGame, ".doorstop_version"), "4.4.0");
            File.WriteAllBytes(loader, Encoding.ASCII.GetBytes("MZ unknown loader\0--doorstop-enabled-spoof\0"));
            Reject(() => PlatformIntegration.DoorstopMajor(loaderGame), "version marker or longer fake option cannot claim bypass support");
            Check(File.ReadAllText(configuration) == "[General]\nenabled = true\n", "vanilla detection does not rewrite or disable config persistently");
            Reject(() => PlatformIntegration.ParseVdf("a { b }"), "missing VDF value");
            Reject(() => PlatformIntegration.ParseVdf("a \"unterminated"), "unterminated VDF quote");
            Reject(() => PlatformIntegration.ParseVdf(string.Concat(Enumerable.Repeat("a { ", 34)) + "x y " + new string('}', 34)), "bounded VDF nesting");
        }
        finally { Directory.Delete(fixture, true); }
        Console.WriteLine($"Platform: {assertions} offline checks passed; Steam and Valheim were not started.");
        return Task.CompletedTask;
    }
}
