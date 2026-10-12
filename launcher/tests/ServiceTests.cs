using System.IO.Compression;
using System.Net;
using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using HearthLauncher.Engine;

namespace HearthLauncher.Tests;

public static class ServiceTests
{
    static int checks;
    static void Check(bool value, string name)
    {
        if (!value) throw new Exception("Service regression: " + name);
        checks++; Console.WriteLine("PASS service: " + name);
    }
    static async Task Reject(Func<Task> action, string name)
    {
        try { await action(); }
        catch (Exception error) when (error is IOException or InvalidDataException or ArgumentException)
        { Check(true, name); return; }
        throw new Exception("Expected rejection: " + name);
    }
    static byte[] Bytes(string text) => Encoding.UTF8.GetBytes(text);
    static string Digest(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    static byte[] Dll(string name, Version version)
    {
        var metadata = new MetadataBuilder();
        metadata.AddModule(0, metadata.GetOrAddString(name + ".dll"), metadata.GetOrAddGuid(Guid.NewGuid()), default, default);
        metadata.AddAssembly(metadata.GetOrAddString(name), version, default, default, (AssemblyFlags)0, (AssemblyHashAlgorithm)0);
        metadata.AddTypeDefinition(TypeAttributes.NotPublic, default, metadata.GetOrAddString("<Module>"), default,
            MetadataTokens.FieldDefinitionHandle(1), MetadataTokens.MethodDefinitionHandle(1));
        var image = new ManagedPEBuilder(new PEHeaderBuilder(imageCharacteristics: Characteristics.ExecutableImage | Characteristics.Dll),
            new MetadataRootBuilder(metadata), new BlobBuilder(), flags: CorFlags.ILOnly);
        var output = new BlobBuilder(); image.Serialize(output); return output.ToArray();
    }
    static byte[] Zip(Dictionary<string, byte[]> files)
    {
        using var output = new MemoryStream();
        using (var archive = new ZipArchive(output, ZipArchiveMode.Create, true))
            foreach (var (path, bytes) in files) { using var stream = archive.CreateEntry(path).Open(); stream.Write(bytes); }
        return output.ToArray();
    }
    static Dictionary<string, byte[]> Full(string addon = "first") => new()
    {
        ["winhttp.dll"] = Bytes("fake loader; never executed"),
        ["doorstop_config.ini"] = Bytes("[General]\nenabled=true"),
        ["BepInEx/core/BepInEx.dll"] = Dll("BepInEx", new(5, 4, 23, 0)),
        ["BepInEx/plugins/HearthMods/Author-Addon/addon.dll"] = Bytes(addon),
        ["hearth-mods.json"] = Bytes("{\"schema\":1}")
    };
    sealed class Network
    {
        public byte[] Bundle = Zip(Full());
        public byte[]? SentBundle;
        public string Mode = "modded";
        public string Mod = "0.11.0.0";
        public byte[] Base = [];
        public string? NextManifest;
        public bool SwitchAfterDownload;
        public int SwitchAtApi;
        public int Downloads, Releases, ApiCalls, ExternalCalls;
        public string Api() => JsonSerializer.Serialize(new
        {
            title = "Northern Hearth", mode = Mode, game = "1.0.17", mod = Mode == "plus" ? Mod : null,
            address = "north.example:2456", community_url = "https://example.org/community", running = true, players = 3,
            client_mods = Mode == "vanilla" ? null : new
            {
                url = "/downloads/Hearth-Client-Mods.zip", sha256 = Digest(Bundle), revision = Digest(Bundle), size = Bundle.Length,
                kind = Mode == "plus" ? "overlay" : "full", packages = new[] { new { id = "Author-Addon", name = "Addon", version = "1.0.0" } }
            }
        });
        public HttpResponseMessage Send(Uri uri)
        {
            byte[] bytes;
            if (uri.AbsoluteUri == "https://north.example/api/public")
            { ApiCalls++; if (ApiCalls == SwitchAtApi) NextManifest = Api().Replace("1.0.17", "1.0.18", StringComparison.Ordinal); bytes = Bytes(NextManifest ?? Api()); }
            else if (uri.AbsoluteUri == "https://north.example/downloads/Hearth-Client-Mods.zip")
            {
                Downloads++; bytes = SentBundle ?? Bundle;
                if (SwitchAfterDownload) NextManifest = Api().Replace("1.0.17", "1.0.18", StringComparison.Ordinal);
            }
            else if (uri.Host == "api.github.com")
            {
                Releases++; bytes = Bytes(JsonSerializer.Serialize(new
                {
                    tag_name = Mod, draft = false, prerelease = false,
                    assets = new[] { new { name = "WindowsClient.zip", browser_download_url = $"https://github.com/Grantapher/ValheimPlus/releases/download/{Mod}/WindowsClient.zip", digest = "sha256:" + Digest(Base) } }
                }));
            }
            else if (uri.Host == "github.com") { Downloads++; bytes = Base; }
            else { ExternalCalls++; throw new IOException("Unexpected fake endpoint: " + uri); }
            return new(HttpStatusCode.OK) { Content = new ByteArrayContent(bytes) };
        }
    }
    sealed class Handler(Network network) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        { token.ThrowIfCancellationRequested(); return Task.FromResult(network.Send(request.RequestUri!)); }
    }
    static string NewGame(string root, string name)
    {
        string game = Path.Combine(root, name); Directory.CreateDirectory(Path.Combine(game, "valheim_Data"));
        File.WriteAllText(Path.Combine(game, "valheim.exe"), "fake game; never executed"); return game;
    }
    static LauncherService Service(string state, Network network, Action<string, string, bool, Action<string>>? launch = null)
        => new(state, _ => new Handler(network), () => { }, launch ?? ((_, _, _, _) => throw new Exception("Game must never launch in this test")));

    public static async Task RunAsync()
    {
        string root = Path.Combine(Path.GetTempPath(), "HearthLauncher-ServiceTests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            await Synchronization(root);
            await ReadOnlyInspection(root);
            await AutomaticPlay(root);
            await BadPayloads(root);
            await PlusAndVanilla(root);
            await Compatibility(root);
            await Transactions(root);
            await Profiles(root);
            Console.WriteLine($"Service tests: {checks} checks passed; no game or external network execution.");
        }
        finally { Directory.Delete(root, true); }
    }

    static async Task Synchronization(string root)
    {
        string game = NewGame(root, "sync"), addon = "BepInEx/plugins/HearthMods/Author-Addon/addon.dll";
        var profile = new LauncherProfile("north", "North", "https://north.example", game);
        var net = new Network(); var service = Service(Path.Combine(root, "sync-state"), net);
        var initial = await service.InspectAsync(profile);
        Check(initial.NeedsSync && initial.ClientState == ClientCollectionState.InstallRequired && initial.LocalGameVersion is null && initial.Server.Title == "Northern Hearth", "inspect custom domain and honest unknown game version");
        var first = await service.SynchronizeAsync(profile);
        Check(first.ChangedFiles == 4 && !first.NeedsSync && net.Downloads == 1, "first generic sync installs complete checked bundle");
        var inventory = Installer.LoadInventory(game)!;
        Check(inventory.Files.Count == 4 && !File.Exists(Path.Combine(game, "hearth-mods.json")), "full inventory excludes ZIP metadata");
        string addonPath = Installer.SafePath(game, addon);
        var stamp = File.GetLastWriteTimeUtc(addonPath);
        int backups = Directory.GetDirectories(Path.Combine(game, ".hearth-launcher", "backups")).Length;
        var noop = await service.SynchronizeAsync(profile);
        Check(noop.ChangedFiles == 0 && net.Downloads == 1 && File.GetLastWriteTimeUtc(addonPath) == stamp, "no-op performs no archive download or rewrite");
        Check(Directory.GetDirectories(Path.Combine(game, ".hearth-launcher", "backups")).Length == backups, "no-op creates no backup");
        File.Delete(addonPath);
        Check((await service.InspectAsync(profile)).ChangedFiles == 1, "missing owned file detected");
        var repair = await service.SynchronizeAsync(profile);
        Check(repair.ChangedFiles == 1 && net.Downloads == 1 && File.ReadAllText(addonPath) == "first", "missing-file repair uses verified cache");
        Check(Installer.LoadInventory(game)!.Files.Count == 4, "repair journal does not replace complete inventory");
        File.WriteAllText(addonPath, "edited");
        Check((await service.SynchronizeAsync(profile)).ChangedFiles == 1, "repair replaces changed selected file");
        await service.RestoreAsync(profile);
        Check(File.ReadAllText(addonPath) == "edited" && (await service.InspectAsync(profile)).NeedsSync, "restore returns pre-repair file and integrity state");
        await service.SynchronizeAsync(profile);
        string config = Installer.SafePath(game, "BepInEx/config/private.cfg"), foreign = Installer.SafePath(game, "BepInEx/plugins/my-mod.dll");
        Directory.CreateDirectory(Path.GetDirectoryName(config)!); Directory.CreateDirectory(Path.GetDirectoryName(foreign)!);
        File.WriteAllText(config, "private config"); File.WriteAllText(foreign, "foreign mod");
        Check((await service.InspectAsync(profile)).Notes.Any(n => n.Contains("вне учёта", StringComparison.Ordinal)), "foreign mods reported");
        net.Bundle = Zip(Full("updated"));
        await service.SynchronizeAsync(profile);
        Check(File.ReadAllText(config) == "private config" && File.ReadAllText(foreign) == "foreign mod", "foreign mods and private configs preserved");
        File.Delete(addonPath);
        string cached = Path.Combine(root, "sync-state", "cache", Digest(net.Bundle) + ".zip");
        File.WriteAllText(cached, "corrupt cache"); int downloads = net.Downloads;
        await service.SynchronizeAsync(profile);
        Check(net.Downloads == downloads + 1 && File.ReadAllBytes(cached).SequenceEqual(net.Bundle), "corrupt cached archive is reverified and replaced");
        net.ApiCalls = 0; net.SwitchAtApi = 2;
        await Reject(() => service.PlayAsync(profile, true), "server change immediately before launch blocks launch");
    }

    static async Task AutomaticPlay(string root)
    {
        string game = NewGame(root, "automatic-play"); var network = new Network();
        var profile = new LauncherProfile("auto", "Automatic", "https://north.example", game);
        int launches = 0;
        var service = Service(Path.Combine(root, "automatic-play-state"), network, (_, address, vanilla, _) =>
        {
            if (address != "north.example:2456" || vanilla || Installer.LoadInventory(game)?.Files.Count != 4)
                throw new Exception("Steam launch must follow complete mod synchronization");
            launches++;
        });
        var report = await service.PlayAsync(profile, true);
        Check(launches == 1 && network.Downloads == 1 && !report.NeedsSync && report.TotalFiles == 4 && report.Server.Title == "Northern Hearth",
            "Play installs a fresh collection before launching and returns server information");
        var repeated = await service.PlayAsync(profile, true);
        Check(launches == 2 && network.Downloads == 1 && repeated.ChangedFiles == 0,
            "repeated Play verifies the installed collection without downloading it again");
    }

    static async Task ReadOnlyInspection(string root)
    {
        string game = NewGame(root, "inspection"), state = Path.Combine(root, "inspection-state");
        var network = new Network(); int gameChecks = 0;
        var service = new LauncherService(state, _ => new Handler(network), () => gameChecks++,
            (_, _, _, _) => throw new Exception("Read-only inspection must never launch a game"));
        var profile = new LauncherProfile("inspect", "Inspect", "https://north.example", "");
        var noFolder = await service.InspectAsync(profile);
        Check(noFolder.ClientState == ClientCollectionState.FolderRequired && noFolder.Server.Running && noFolder.Server.Players == 3
            && noFolder.Server.Game == "1.0.17", "server cards are available before a game folder is selected");
        var badFolder = await service.InspectAsync(profile with { GamePath = Path.Combine(root, "missing-game") });
        Check(badFolder.ClientState == ClientCollectionState.CheckFailed && badFolder.NeedsSync && !string.IsNullOrEmpty(badFolder.ClientCheckError)
            && badFolder.Server.Title == "Northern Hearth", "invalid selected game folder cannot be reported ready and preserves server data");
        Check(!Directory.Exists(state) && network.Downloads == 0 && network.Releases == 0 && gameChecks == 0,
            "startup and folder checks neither create cache or install state nor fetch archives or require the game closed");
        profile = profile with { GamePath = game };
        var initial = await service.InspectAsync(profile);
        Check(initial.ClientState == ClientCollectionState.InstallRequired && initial.TotalFiles == 0 && !Directory.Exists(Path.Combine(game, ".hearth-launcher")),
            "fresh client requires installation without creating game files");
        await service.SynchronizeAsync(profile);
        int downloads = network.Downloads, closedChecks = gameChecks;
        Dictionary<string, (string Digest, DateTime Modified)> Tree() => Directory.GetFiles(game, "*", SearchOption.AllDirectories)
            .ToDictionary(path => Path.GetRelativePath(game, path), path => (Installer.Hash(path), File.GetLastWriteTimeUtc(path)));
        var before = Tree();
        var ready = await service.InspectAsync(profile);
        Check(ready.ClientState == ClientCollectionState.Ready && !ready.NeedsSync && ready.TotalFiles == 4 && ready.ChangedFiles == 0,
            "automatic client check verifies the complete installed collection");
        var after = Tree();
        Check(before.Count == after.Count && before.All(item => after.TryGetValue(item.Key, out var value) && value == item.Value)
            && network.Downloads == downloads && gameChecks == closedChecks, "ready inspection leaves file bytes and timestamps unchanged with no downloads or game process check");
        string addon = Installer.SafePath(game, "BepInEx/plugins/HearthMods/Author-Addon/addon.dll");
        File.WriteAllText(addon, "modified without touching the inventory");
        var damaged = await service.InspectAsync(profile);
        Check(damaged.ClientState == ClientCollectionState.UpdateRequired && damaged.NeedsSync && damaged.ChangedFiles == 1
            && File.ReadAllText(addon) == "modified without touching the inventory", "inspection hashes actual managed files and does not repair changed content");
        File.WriteAllText(addon, "first");
        network.Bundle = Zip(Full("server changed"));
        var stale = await service.InspectAsync(profile);
        Check(stale.ClientState == ClientCollectionState.UpdateRequired && stale.ChangedFiles == 0 && stale.NeedsSync,
            "changed server manifest requires synchronization even when local file hashes match the old inventory");
        var inventory = Installer.LoadInventory(game)!;
        network.Bundle = Zip(Full());
        // Match the exact original manifest, then vary only ownership metadata.
        inventory = inventory with { Manifest = Installer.ManifestKey(SourceClient.ParseServer(Bytes(network.Api()))) };
        string inventoryPath = Installer.SafePath(game, ".hearth-launcher/inventory.json");
        Installer.WriteJson(inventoryPath, inventory with { Website = "https://south.example" });
        Check((await service.InspectAsync(profile)).ClientState == ClientCollectionState.UpdateRequired,
            "another server's installed inventory is not treated as ready");
        Installer.WriteJson(inventoryPath, inventory with { Mode = "plus" });
        Check((await service.InspectAsync(profile)).ClientState == ClientCollectionState.UpdateRequired,
            "inconsistent inventory mode is not treated as ready");
        File.WriteAllText(inventoryPath, "broken inventory");
        var broken = await service.InspectAsync(profile);
        Check(broken.ClientState == ClientCollectionState.CheckFailed && broken.NeedsSync && broken.Server.Running && !string.IsNullOrEmpty(broken.ClientCheckError),
            "unreadable inventory reports a failed client check while keeping server state");
        network.Mode = "vanilla";
        var vanilla = await service.InspectAsync(profile);
        Check(vanilla.ClientState == ClientCollectionState.NotRequired && !vanilla.NeedsSync && File.ReadAllText(inventoryPath) == "broken inventory",
            "vanilla needs no mod collection and does not read or rewrite unused mod inventory");
        using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
        try { await service.InspectAsync(profile, cancelled.Token); throw new Exception("Cancellation must be observed"); }
        catch (OperationCanceledException) { Check(true, "cancelled inspection propagates cancellation instead of reporting a failed or ready client"); }
        Check(network.Downloads == downloads && gameChecks == closedChecks && network.ExternalCalls == 0,
            "all background client states are read-only and use only the server public API");
    }

    static async Task BadPayloads(string root)
    {
        foreach (string kind in new[] { "changed-server", "bad-hash", "traversal" })
        {
            string game = NewGame(root, kind); var net = new Network();
            if (kind == "changed-server") net.SwitchAfterDownload = true;
            if (kind == "bad-hash") net.SentBundle = Bytes("wrong archive");
            if (kind == "traversal") { var files = Full(); files["../escaped.dll"] = Bytes("bad"); net.Bundle = Zip(files); }
            var service = Service(Path.Combine(root, kind + "-state"), net);
            await Reject(() => service.SynchronizeAsync(new(kind, kind, "https://north.example", game)), kind + " rejected");
            Check(!File.Exists(Path.Combine(game, "winhttp.dll")) && !File.Exists(Path.Combine(game, ".hearth-launcher", "inventory.json")), kind + " cannot modify game");
        }
        Check(!File.Exists(Path.Combine(root, "escaped.dll")), "ZIP traversal creates no escaped file");
        string collisionGame = NewGame(root, "foreign-collision");
        string collision = Installer.SafePath(collisionGame, "BepInEx/plugins/HearthMods/Author-Addon/addon.dll");
        Directory.CreateDirectory(Path.GetDirectoryName(collision)!); File.WriteAllText(collision, "foreign content");
        var collisionService = Service(Path.Combine(root, "foreign-collision-state"), new Network());
        await Reject(() => collisionService.SynchronizeAsync(new("collision", "Collision", "https://north.example", collisionGame)), "unowned HearthMods collision blocks replacement");
        Check(File.ReadAllText(collision) == "foreign content" && !File.Exists(Path.Combine(collisionGame, "winhttp.dll")), "foreign collision preserves foreign file and game payload");
        await Reject(() => Task.Run(() => SourceClient.Endpoint("https://north.example/path")), "non-origin website rejected");
        await Reject(() => Task.Run(() => Installer.SafePath(root, "BepInEx/test:stream")), "portable path rejects alternate stream");
    }

    static async Task PlusAndVanilla(string root)
    {
        string game = NewGame(root, "plus"); var net = new Network { Mode = "plus" };
        var files = Full(); files.Remove("BepInEx/plugins/HearthMods/Author-Addon/addon.dll"); files.Remove("hearth-mods.json");
        files["BepInEx/plugins/ValheimPlus.dll"] = Dll("ValheimPlus", new(0, 11, 0, 0));
        files["BepInEx/config/valheim_plus.cfg"] = Bytes("server package default");
        net.Base = Zip(files);
        net.Bundle = Zip(new() { ["BepInEx/plugins/HearthMods/Author-Addon/addon.dll"] = Bytes("overlay") });
        string config = Installer.SafePath(game, "BepInEx/config/valheim_plus.cfg");
        Directory.CreateDirectory(Path.GetDirectoryName(config)!); File.WriteAllText(config, "my config");
        var profile = new LauncherProfile("plus", "Plus", "https://north.example", game);
        var service = Service(Path.Combine(root, "plus-state"), net);
        await service.SynchronizeAsync(profile);
        Check(File.ReadAllText(config) == "my config" && Installer.ExistingMod(game) == "0.11.0.0", "exact V+ base plus overlay preserves existing config");
        int count = net.Downloads;
        await service.SynchronizeAsync(profile);
        Check(net.Downloads == count && net.Releases == 1, "unchanged V+ skips GitHub and bundle archives");
        net.Mode = "modded"; net.Bundle = Zip(Full("generic"));
        await service.SynchronizeAsync(profile);
        Check(!File.Exists(Installer.SafePath(game, "BepInEx/plugins/ValheimPlus.dll")), "switch to generic removes only owned unchanged V+");
        await service.RestoreAsync(profile);
        net.Mode = "plus";
        net.Bundle = Zip(new() { ["BepInEx/plugins/HearthMods/Author-Addon/addon.dll"] = Bytes("overlay") });
        Check(File.Exists(Installer.SafePath(game, "BepInEx/plugins/ValheimPlus.dll")) && !(await service.InspectAsync(profile)).NeedsSync, "restore recovers complete previous Plus inventory");
        net.Mode = "vanilla"; count = net.Downloads; string before = File.ReadAllText(config);
        bool launched = false;
        var vanilla = Service(Path.Combine(root, "vanilla-state"), net, (_, address, mode, _) =>
        { launched = address == "north.example:2456" && mode; });
        var result = await vanilla.SynchronizeAsync(profile);
        await vanilla.PlayAsync(profile, true);
        Check(!result.NeedsSync && net.Downloads == count && File.ReadAllText(config) == before && launched, "vanilla neither downloads nor mutates mods; launch plan receives validated endpoint");
        await Reject(() => vanilla.PlayAsync(profile with { AddressOverride = "north.example:2456 +exec" }, true), "launch rejects injected address");
    }

    static async Task Compatibility(string root)
    {
        string game = NewGame(root, "compatibility"); var net = new Network();
        var profile = new LauncherProfile("compat", "Compatibility", "https://north.example", game);
        bool launched = false;
        var service = Service(Path.Combine(root, "compat-state"), net, (_, _, _, _) => launched = true);
        await service.SynchronizeAsync(profile);
        int downloads = net.Downloads;
        string inventory = File.ReadAllText(Path.Combine(game, ".hearth-launcher", "inventory.json"));
        string plus = Installer.SafePath(game, "BepInEx/plugins/ValheimPlus.dll");
        File.WriteAllBytes(plus, Dll("ValheimPlus", new(0, 11, 0, 0)));
        var conflict = await service.InspectAsync(profile);
        Check(conflict.ClientState == ClientCollectionState.CheckFailed && conflict.NeedsSync && !string.IsNullOrEmpty(conflict.ClientCheckError)
            && conflict.Server.Title == "Northern Hearth", "inspect detects manually added V+ and preserves server status without claiming readiness");
        await Reject(() => service.SynchronizeAsync(profile), "no-op cannot bypass manually added V+");
        await Reject(() => service.PlayAsync(profile, true), "manually added V+ blocks Steam launch");
        Check(!launched && net.Downloads == downloads && File.ReadAllText(Path.Combine(game, ".hearth-launcher", "inventory.json")) == inventory,
            "conflicting V+ rejection performs no download, install or launch");
        File.Delete(plus);
        string duplicate = Installer.SafePath(game, "BepInEx/plugins/other/ValheimPlus.dll");
        Directory.CreateDirectory(Path.GetDirectoryName(duplicate)!); File.WriteAllText(duplicate, "unreadable duplicate");
        await Reject(() => service.PlayAsync(profile, true), "nested V+ filename blocks launch even without readable assembly metadata");
        File.Delete(duplicate);
        if (!OperatingSystem.IsWindows())
        {
            string lower = NewGame(root, "case-conflict");
            Directory.CreateDirectory(Path.Combine(lower, "bepinex", "plugins"));
            File.WriteAllText(Path.Combine(lower, "bepinex", "plugins", "foreign.dll"), "preserve");
            await Reject(() => service.SynchronizeAsync(profile with { GamePath = lower }), "Proton case-alias folder blocks installation");
            Check(!Directory.Exists(Path.Combine(lower, "BepInEx")) && File.ReadAllText(Path.Combine(lower, "bepinex", "plugins", "foreign.dll")) == "preserve",
                "case conflict preserves original folder and files");
            string core = Path.Combine(game, "BepInEx", "core", "BepInEx.dll");
            File.Move(core, Path.Combine(Path.GetDirectoryName(core)!, "bepinex.dll"));
            await Reject(() => service.PlayAsync(profile, true), "Proton case-alias file blocks no-op launch");
        }
    }

    static async Task Transactions(string root)
    {
        string game = NewGame(root, "transactions"), stage = Path.Combine(root, "transaction-stage");
        var files = Installer.Extract(Zip(Full()), stage, false);
        var server = new ServerVersion("1.0.17", null, "modded");
        var desired = new InstallationInventory(1, game, "https://north.example", Installer.ManifestKey(server), "modded",
            files.Select(f => new OwnedFile(f, Installer.Hash(Installer.SafePath(stage, f)))).ToList());
        await Reject(() => Task.Run(() => Installer.Apply(game, stage, files, desired, _ => { }, () => { }, n =>
        { if (n == 1) throw new IOException("Injected copy interruption"); })), "partial install rolls back");
        Check(!File.Exists(Path.Combine(game, "winhttp.dll")) && Installer.LoadInventory(game) is null, "failed first transaction restores files and absent inventory");
        Installer.Apply(game, stage, files, desired, _ => { }, () => { });
        string inventory = File.ReadAllText(Path.Combine(game, ".hearth-launcher", "inventory.json"));
        File.WriteAllText(Installer.SafePath(stage, "winhttp.dll"), "new loader");
        var changed = desired with { Files = files.Select(f => new OwnedFile(f, Installer.Hash(Installer.SafePath(stage, f)))).ToList(), Manifest = new string('A', 64) };
        Installer.Apply(game, stage, files, changed, _ => { }, () => { });
        Installer.Restore(game, () => { });
        Check(File.ReadAllText(Path.Combine(game, ".hearth-launcher", "inventory.json")) == inventory && File.ReadAllText(Path.Combine(game, "winhttp.dll")) == "fake loader; never executed", "restore returns complete inventory despite unchanged files omitted from journal");
        string backup = Installer.LatestBackup(game)!;
        var journal = JsonSerializer.Deserialize<Journal>(File.ReadAllText(Path.Combine(backup, "journal.json")))!;
        Installer.WriteJson(Path.Combine(backup, "journal.json"), journal with { State = "installing" });
        await Reject(() => Task.Run(() => Installer.EnsureRecovered(game)), "interrupted transaction blocks otherwise-valid inventory");
    }

    static async Task Profiles(string root)
    {
        var store = new ProfileStore(Path.Combine(root, "profiles"));
        Check(store.Load().Profiles.Single().Website == "https://loki.ach-play.ru", "Loki is only the editable default profile");
        var settings = new LauncherSettings("en", [new("north", "North", "https://north.example", ""), new("south", "South", "https://south.example", "")], "south");
        store.Save(settings);
        Check(store.Load().SelectedProfileId == "south" && store.Load().Profiles.Count == 2 && store.Load().Language == "en", "profiles and selected language persist");
        await Reject(() => Task.Run(() => store.Save(settings with { Profiles = [new("north", "Bad", "http://north.example", "")] })), "invalid profile cannot replace settings");
        Check(store.Load().Profiles.Count == 2, "failed save preserves previous settings");
    }
}
