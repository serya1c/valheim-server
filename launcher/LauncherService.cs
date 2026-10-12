using HearthLauncher.Engine;
using System.Security.Cryptography;

namespace HearthLauncher;

public sealed class LauncherService : ILauncherService
{
    readonly string stateDirectory;
    readonly Func<string, HttpMessageHandler>? httpHandlerFactory;
    readonly Action ensureGameClosed;
    readonly Action<string, string, bool, Action<string>> launchGame;
    readonly SemaphoreSlim gate = new(1, 1);
    public event Action<string>? Log;

    public LauncherService(string? stateDirectory = null, Func<string, HttpMessageHandler>? httpHandlerFactory = null,
        Action? ensureGameClosed = null, Action<string, string, bool, Action<string>>? launchGame = null)
    {
        this.stateDirectory = Path.GetFullPath(stateDirectory ?? PlatformIntegration.DefaultStateDirectory);
        this.httpHandlerFactory = httpHandlerFactory;
        this.ensureGameClosed = ensureGameClosed ?? PlatformIntegration.EnsureGameClosed;
        this.launchGame = launchGame ?? PlatformIntegration.LaunchGame;
    }

    public static string ValidateAddress(string address) => PlatformIntegration.NormalizeAddress(address);
    void Write(string text) => Log?.Invoke(text);
    static string Website(LauncherProfile profile) => new Uri(SourceClient.Endpoint(profile.Website)).GetLeftPart(UriPartial.Authority);
    SourceClient Source(string website) => new(website, httpHandlerFactory?.Invoke(website));
    static string Game(LauncherProfile profile)
    {
        if (string.IsNullOrWhiteSpace(profile.GamePath)) throw new IOException("Выберите папку Steam-версии Valheim.");
        string game = OperatingSystem.IsLinux() ? PlatformIntegration.CanonicalDirectory(profile.GamePath) : Installer.Root(profile.GamePath);
        Installer.NoLinks(game);
        if (!Installer.IsGame(game)) throw new IOException("Нужна папка с valheim.exe и valheim_Data.");
        Installer.NoLinks(Path.Combine(game, "valheim.exe"));
        Installer.NoLinks(Path.Combine(game, "valheim_Data"));
        return game;
    }
    static ServerSnapshot Snapshot(LauncherProfile profile, string website, ServerVersion version) => new(version.Title, website,
        string.IsNullOrEmpty(profile.AddressOverride) ? version.Address : profile.AddressOverride,
        version.Game, version.Mod, version.Mode, version.Running, version.Players, version.CommunityUrl,
        version.ClientMods?.Packages.Select(p => p.Name + " " + p.Version).ToArray() ?? []);

    public async Task<LauncherReport> InspectAsync(LauncherProfile profile, CancellationToken cancellationToken = default)
    {
        await gate.WaitAsync(cancellationToken);
        try
        {
            string website = Website(profile), game = Game(profile);
            using var source = Source(website);
            var version = await source.Server(cancellationToken);
            return await Task.Run(() => Report(profile, website, game, version), cancellationToken);
        }
        finally { gate.Release(); }
    }

    static LauncherReport Report(LauncherProfile profile, string website, string game, ServerVersion version,
        int? changes = null, int? total = null)
    {
        var inventory = Installer.LoadInventory(game);
        var notes = new List<string> { "Версия установленной игры не определена. Обновление Valheim выполняет Steam." };
        if (!version.Running) notes.Add("Сервер сейчас остановлен.");
        if (!OperatingSystem.IsWindows()) notes.Add("Для модов включите Proton и один раз задайте в Steam: WINEDLLOVERRIDES=\"winhttp=n,b\" %command%.");
        notes.Add("Профили используют общую папку игры и общие конфигурации модов.");
        if (version.Mode == "vanilla")
        {
            notes.Add("Ванильный режим не меняет файлы. Загрузчик модов отключается только для этого запуска.");
            return new(Snapshot(profile, website, version), 0, 0, false, null, notes);
        }
        Installer.EnsureRecovered(game);
        Installer.ValidateCompatibility(game, version.Mode, inventory);
        int different = inventory is null ? 0 : Installer.DifferentFiles(game, inventory);
        bool matches = Installer.InventoryMatches(game, website, version, inventory);
        if (ForeignPlugins(game, inventory)) notes.Add("Найдены моды вне учёта лаунчера. Они сохраняются и могут влиять на совместимость.");
        if (!matches) notes.Add("Моды предоставлены выбранным сервером и выполняются на вашем компьютере.");
        return new(Snapshot(profile, website, version), changes ?? different, total ?? inventory?.Files.Count ?? 0,
            !matches, null, notes);
    }

    static bool ForeignPlugins(string game, InstallationInventory? inventory)
    {
        string plugins = Installer.SafePath(game, "BepInEx/plugins");
        if (!Directory.Exists(plugins)) return false;
        var owned = new HashSet<string>(inventory?.Files.Select(f => f.Path) ?? [], StringComparer.OrdinalIgnoreCase);
        bool Walk(string folder)
        {
            foreach (string path in Directory.EnumerateFileSystemEntries(folder))
            {
                Installer.NoLinks(path);
                if (Directory.Exists(path)) { if (Walk(path)) return true; }
                else if (path.EndsWith(".dll", StringComparison.OrdinalIgnoreCase)
                    && !owned.Contains(Path.GetRelativePath(game, path).Replace('\\', '/'))) return true;
            }
            return false;
        }
        return Walk(plugins);
    }

    public async Task<LauncherReport> SynchronizeAsync(LauncherProfile profile, CancellationToken cancellationToken = default)
    {
        await gate.WaitAsync(cancellationToken);
        try { return await Synchronize(profile, cancellationToken); }
        finally { gate.Release(); }
    }

    async Task<LauncherReport> Synchronize(LauncherProfile profile, CancellationToken cancellationToken)
    {
        string website = Website(profile), game = Game(profile);
        using var source = Source(website);
        var selected = await source.Server(cancellationToken);
        if (selected.Mode == "vanilla")
        {
            Write("Ванильный сервер: установка модов не требуется.");
            return Report(profile, website, game, selected);
        }
        Installer.EnsureRecovered(game);
        var inventory = Installer.LoadInventory(game);
        await Task.Run(() => Installer.ValidateCompatibility(game, selected.Mode, inventory), cancellationToken);
        if (await Task.Run(() => Installer.InventoryMatches(game, website, selected, inventory), cancellationToken))
        {
            Write("Все файлы модов проверены. Синхронизация не требуется.");
            return Report(profile, website, game, selected, 0);
        }
        await Task.Run(() => { Installer.ValidateTarget(game, false); ensureGameClosed(); }, cancellationToken);
        string stages = Path.Combine(stateDirectory, "staging");
        Installer.NoLinks(stages); Directory.CreateDirectory(stages);
        string stage = Installer.SafePath(stages, Guid.NewGuid().ToString("N"));
        try
        {
            var files = new List<string>();
            if (selected.Mode == "plus")
            {
                Write("Проверяем официальный клиентский пакет Valheim Plus.");
                var asset = await source.Release(selected, cancellationToken);
                var bytes = await Cached(asset.Sha256, null, () => source.DownloadAsset(asset, cancellationToken), cancellationToken);
                files.AddRange(await Task.Run(() => Installer.Extract(bytes, stage), cancellationToken));
            }
            if (selected.ClientMods is { } bundle)
            {
                Write("Проверяем клиентский набор модов сервера.");
                var bytes = await Cached(bundle.Sha256, bundle.Size, () => source.DownloadBundle(bundle, cancellationToken), cancellationToken);
                files.AddRange(await Task.Run(() => Installer.Extract(bytes, stage, selected.Mode == "plus", bundle.Kind == "overlay"), cancellationToken));
            }
            await Task.Run(() => Installer.ValidatePayload(stage, selected.Mod), cancellationToken);
            if (files.Count > 5000 || files.Sum(path => new FileInfo(Installer.SafePath(stage, path)).Length) > 512L * 1024 * 1024)
                throw new IOException("Полный клиентский набор превышает допустимый размер.");
            var complete = files.Select(path => new OwnedFile(path, Installer.Hash(Installer.SafePath(stage, path)))).ToList();
            var desired = new InstallationInventory(1, game, website, Installer.ManifestKey(selected), selected.Mode, complete);
            if (!selected.SameAs(await source.Server(cancellationToken)))
                throw new IOException("Версии или набор модов сервера изменились во время загрузки. Повторите синхронизацию.");
            cancellationToken.ThrowIfCancellationRequested();
            // Once writes start, the complete transaction finishes or rolls back.
            var applied = await Task.Run(() => Installer.Apply(game, stage, files, desired, Write, ensureGameClosed));
            Write("Синхронизация завершена. Резервная копия: " + applied.Backup);
            return Report(profile, website, game, selected, applied.ChangedFiles, applied.TotalFiles);
        }
        finally { if (Directory.Exists(stage)) { Installer.NoLinks(stage); Directory.Delete(stage, true); } }
    }

    async Task<byte[]> Cached(string hash, long? size, Func<Task<byte[]>> download, CancellationToken cancellationToken)
    {
        string folder = Path.Combine(stateDirectory, "cache");
        Installer.NoLinks(folder); Directory.CreateDirectory(folder);
        string path = Installer.SafePath(folder, hash.ToLowerInvariant() + ".zip");
        if (File.Exists(path))
        {
            long length = new FileInfo(path).Length;
            if (length > 0 && length <= 128L * 1024 * 1024 && (size is null || length == size))
            {
                var cached = await File.ReadAllBytesAsync(path, cancellationToken);
                if (Convert.ToHexString(SHA256.HashData(cached)).Equals(hash, StringComparison.OrdinalIgnoreCase))
                { Write("Используем проверенный архив из кеша."); return cached; }
            }
            File.Delete(path);
        }
        var bytes = await download();
        if (bytes.Length is < 1 or > 134217728 || size is not null && bytes.LongLength != size)
            throw new IOException("Размер скачанного архива не совпадает.");
        SourceClient.VerifyHash(bytes, hash);
        cancellationToken.ThrowIfCancellationRequested();
        string temporary = path + "." + Guid.NewGuid().ToString("N");
        try
        {
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { await stream.WriteAsync(bytes, cancellationToken); stream.Flush(true); }
            File.Move(temporary, path, true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
        return bytes;
    }

    public async Task RestoreAsync(LauncherProfile profile, CancellationToken cancellationToken = default)
    {
        await gate.WaitAsync(cancellationToken);
        try
        {
            string game = Game(profile); cancellationToken.ThrowIfCancellationRequested();
            string backup = await Task.Run(() => Installer.Restore(game, ensureGameClosed));
            Write("Файлы и сведения об установленном наборе восстановлены: " + backup);
        }
        finally { gate.Release(); }
    }

    public async Task PlayAsync(LauncherProfile profile, bool connect, CancellationToken cancellationToken = default)
    {
        await gate.WaitAsync(cancellationToken);
        try
        {
            var report = await Synchronize(profile, cancellationToken);
            using var source = Source(Website(profile));
            var latest = await source.Server(cancellationToken);
            string game = Game(profile);
            if (latest.Game != report.Server.Game || latest.Mod != report.Server.Mod || latest.Mode != report.Server.Mode
                || latest.Mode != "vanilla" && !Installer.InventoryMatches(game, Website(profile), latest, Installer.LoadInventory(game)))
                throw new IOException("Сервер изменился после синхронизации. Повторите запуск.");
            string address = connect ? ValidateAddress(string.IsNullOrEmpty(profile.AddressOverride) ? latest.Address : profile.AddressOverride) : "";
            if (connect && address.Length == 0) throw new IOException("Адрес подключения не задан. Укажите его в профиле сервера.");
            cancellationToken.ThrowIfCancellationRequested();
            await Task.Run(() => { Installer.ValidateCompatibility(game, latest.Mode, Installer.LoadInventory(game)); ensureGameClosed(); launchGame(game, address, latest.Mode == "vanilla", Write); }, cancellationToken);
        }
        finally { gate.Release(); }
    }
}
