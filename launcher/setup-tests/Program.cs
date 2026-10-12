using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using HearthLauncherSetup;

string root = Path.Combine(Path.GetTempPath(), "hearth-setup-test-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
int passed = 0;
try
{
    byte[] Zip(string version, bool unexpected = false)
    {
        using var memory = new MemoryStream();
        using (var archive = new ZipArchive(memory, ZipArchiveMode.Create, true))
            foreach (var (name, data) in new[] { ("Hearth-Launcher.exe", "MZ" + version), ("hearth.ico", "ICO"), ("README.md", "README") }
                         .Concat(unexpected ? [("../escape", "BAD")] : []))
            { using var output = archive.CreateEntry(name).Open(); output.Write(Encoding.UTF8.GetBytes(data)); }
        return memory.ToArray();
    }
    InstallationPaths Paths(string test) => new(Path.Combine(root, test, "program"), Path.Combine(root, test, "desktop"), Path.Combine(root, test, "menu"));
    void Install(byte[] zip, InstallationPaths paths, Action<InstallationPaths>? shortcuts = null) =>
        Installation.Install(zip, Convert.ToHexString(SHA256.HashData(zip)), Encoding.UTF8.GetBytes("# uninstall"), paths, shortcuts ?? (_ => { }));
    void Assert(bool value) { if (!value) throw new Exception("Assertion failed."); passed++; }
    void Fails(Action operation)
    {
        try { operation(); } catch (Exception error) when (error is IOException or InvalidDataException) { passed++; return; }
        throw new Exception("Unsafe installation was accepted.");
    }

    var paths = Paths("normal");
    int callbacks = 0;
    Install(Zip("v1"), paths, _ => callbacks++);
    Assert(callbacks == 1 && File.ReadAllText(Path.Combine(paths.Directory, "Hearth-Launcher.exe")) == "MZv1");
    Assert(File.ReadAllBytes(Path.Combine(paths.Directory, "uninstall.ps1")).Take(3).SequenceEqual(new byte[] { 0xEF, 0xBB, 0xBF }));
    string profile = Path.Combine(root, "profiles.json"); File.WriteAllText(profile, "keep profile");
    Install(Zip("v2"), paths);
    Assert(File.ReadAllText(Path.Combine(paths.Directory, "Hearth-Launcher.exe")) == "MZv2" && File.ReadAllText(profile) == "keep profile");
    Fails(() => Install(Zip("v3"), paths, _ => throw new IOException("simulated shortcut failure")));
    Assert(File.ReadAllText(Path.Combine(paths.Directory, "Hearth-Launcher.exe")) == "MZv2");
    var fresh = Paths("newfailure"); Fails(() => Install(Zip("new"), fresh, _ => throw new IOException("fail")));
    Assert(!Directory.Exists(fresh.Directory));
    File.WriteAllText(Path.Combine(paths.Directory, "personal.txt"), "preserve");
    Fails(() => Install(Zip("v4"), paths));
    Assert(File.ReadAllText(Path.Combine(paths.Directory, "personal.txt")) == "preserve");
    var unowned = Paths("unowned"); Directory.CreateDirectory(unowned.Directory); File.WriteAllText(Path.Combine(unowned.Directory, "personal.txt"), "keep");
    Fails(() => Install(Zip("v1"), unowned));
    var traversal = Paths("traversal"); Fails(() => Install(Zip("v1", unexpected: true), traversal));
    Assert(!Directory.Exists(traversal.Directory));
    byte[] damaged = Zip("damaged");
    Fails(() => Installation.Install(damaged, new string('0', 64), [], Paths("hash"), _ => { }));
    var locked = Paths("locked"); Install(Zip("v1"), locked);
    using (var handle = new FileStream(Path.Combine(locked.Directory, "Hearth-Launcher.exe"), FileMode.Open, FileAccess.Read, FileShare.None))
        Fails(() => Install(Zip("v2"), locked));
    Assert(File.ReadAllText(Path.Combine(locked.Directory, "Hearth-Launcher.exe")) == "MZv1");
    if (!OperatingSystem.IsWindows())
    {
        var linked = Paths("linked"); Directory.CreateDirectory(Path.GetDirectoryName(linked.Directory)!);
        Directory.CreateSymbolicLink(linked.Directory, Path.Combine(root, "missing"));
        Fails(() => Install(Zip("v1"), linked)); File.Delete(linked.Directory);
    }
    Console.WriteLine($"PASS {passed} isolated setup checks; no desktop, registry, Steam or game writes.");
}
finally
{
    string resolved = Path.GetFullPath(root);
    if (!resolved.StartsWith(Path.GetFullPath(Path.GetTempPath()), StringComparison.OrdinalIgnoreCase)
        || !Path.GetFileName(resolved).StartsWith("hearth-setup-test-", StringComparison.Ordinal)) throw new IOException("Unsafe test cleanup.");
    Directory.Delete(root, true);
}
