using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace HearthLauncherSetup;

public sealed record InstallationPaths(string Directory, string Desktop, string Menu);

public static class Installation
{
    const string Marker = ".hearth-launcher-install.json";
    static readonly string[] PayloadNames = ["Hearth-Launcher.exe", "hearth.ico", "README.md"];
    static readonly string[] OwnedNames = [.. PayloadNames, "uninstall.ps1", Marker];
    public const string Product = "HearthLauncher";

    public static InstallationPaths DefaultPaths() => new(
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", Product),
        Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
        Environment.GetFolderPath(Environment.SpecialFolder.Programs));

    public static void Install(byte[] payload, string digest, byte[] uninstall, InstallationPaths paths,
        Action<InstallationPaths> shortcuts)
    {
        if (payload.Length is 0 or > 100 * 1024 * 1024 || digest.Length != 64
            || !string.Equals(Convert.ToHexString(SHA256.HashData(payload)), digest, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("SHA-256: повреждён установщик / The setup payload is damaged.");
        string target = Path.GetFullPath(paths.Directory);
        string parent = Path.GetDirectoryName(target) ?? throw new IOException("Invalid installation directory.");
        foreach (string path in new[] { target, paths.Desktop, paths.Menu }) NoLinks(path);
        if (Directory.Exists(target)) ValidateExisting(target);
        Directory.CreateDirectory(parent);
        string lockPath = Path.Combine(parent, ".hearth-launcher-setup.lock");
        NoLinks(lockPath);
        using var installationLock = new FileStream(lockPath, FileMode.OpenOrCreate, FileAccess.ReadWrite,
            FileShare.None, 1, FileOptions.DeleteOnClose);
        string stage = Path.Combine(parent, ".hearth-stage-" + Guid.NewGuid().ToString("N"));
        string old = Path.Combine(parent, ".hearth-previous-" + Guid.NewGuid().ToString("N"));
        bool movedOld = false, installed = false;
        try
        {
            Directory.CreateDirectory(stage);
            using var archive = new ZipArchive(new MemoryStream(payload), ZipArchiveMode.Read);
            if (archive.Entries.Count != PayloadNames.Length
                || !archive.Entries.Select(e => e.FullName).Order().SequenceEqual(PayloadNames.Order()))
                throw new InvalidDataException("Unexpected installer payload.");
            foreach (var entry in archive.Entries)
            {
                if (entry.Length is <= 0 or > 120 * 1024 * 1024 || ((entry.ExternalAttributes >> 16) & 0xF000) == 0xA000)
                    throw new InvalidDataException("Invalid payload entry.");
                using var input = entry.Open();
                using var output = new FileStream(Path.Combine(stage, entry.FullName), FileMode.CreateNew);
                input.CopyTo(output);
                if (output.Length != entry.Length) throw new InvalidDataException("Truncated installer payload.");
                output.Flush(true);
            }
            byte[] executable = File.ReadAllBytes(Path.Combine(stage, "Hearth-Launcher.exe"));
            if (executable.Length < 2 || executable[0] != 'M' || executable[1] != 'Z')
                throw new InvalidDataException("The Windows launcher executable is missing.");
            // Windows PowerShell 5.1 needs a BOM to read the bilingual UTF-8 script.
            File.WriteAllBytes(Path.Combine(stage, "uninstall.ps1"), [0xEF, 0xBB, 0xBF, .. uninstall]);
            File.WriteAllText(Path.Combine(stage, Marker), JsonSerializer.Serialize(new { product = Product, version = "1.1.1" }), new UTF8Encoding(false));
            NoLinks(target);
            if (Directory.Exists(target))
            {
                ValidateExisting(target);
                // Windows refuses the exclusive handle when the launcher is running.
                using (new FileStream(Path.Combine(target, "Hearth-Launcher.exe"), FileMode.Open, FileAccess.ReadWrite, FileShare.None)) { }
                Directory.Move(target, old); movedOld = true;
            }
            Directory.Move(stage, target); installed = true;
            shortcuts(paths with { Directory = target });
            if (movedOld)
            {
                // The new installation is complete; a failed cleanup must not roll it back.
                try { RemoveOwnedDirectory(old); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }
        catch
        {
            if (installed) RemoveOwnedDirectory(target);
            if (movedOld && Directory.Exists(old)) Directory.Move(old, target);
            throw;
        }
        finally
        {
            // A random, newly created directory containing only the setup's known files.
            if (Directory.Exists(stage)) RemoveOwnedDirectory(stage, requireMarker: false);
        }
    }

    public static void NoLinks(string path)
    {
        string? cursor = Path.GetFullPath(path);
        while (cursor is not null)
        {
            try
            {
                if ((File.GetAttributes(cursor) & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("Installation paths cannot contain links: " + cursor);
            }
            catch (FileNotFoundException) { }
            catch (DirectoryNotFoundException) { }
            cursor = Path.GetDirectoryName(cursor);
        }
    }

    static void ValidateExisting(string directory)
    {
        NoLinks(directory);
        string marker = Path.Combine(directory, Marker);
        NoLinks(marker);
        if (!File.Exists(marker) || new FileInfo(marker).Length > 4096)
            throw new IOException("Installation directory is not owned by Hearth Setup.");
        using var document = JsonDocument.Parse(File.ReadAllBytes(marker));
        if (document.RootElement.GetProperty("product").GetString() != Product)
            throw new IOException("Installation marker is invalid.");
        ValidateContents(directory);
        if (!File.Exists(Path.Combine(directory, "Hearth-Launcher.exe"))) throw new IOException("Previous installation is incomplete.");
    }

    static void ValidateContents(string directory)
    {
        foreach (string path in Directory.EnumerateFileSystemEntries(directory))
        {
            NoLinks(path);
            if (Directory.Exists(path) || !OwnedNames.Contains(Path.GetFileName(path), StringComparer.Ordinal))
                throw new IOException("Unrecognized files in installation directory; move them first: " + path);
        }
    }

    static void RemoveOwnedDirectory(string directory, bool requireMarker = true)
    {
        if (requireMarker) ValidateExisting(directory); else ValidateContents(directory);
        foreach (string path in Directory.EnumerateFiles(directory)) File.Delete(path);
        Directory.Delete(directory);
    }
}
