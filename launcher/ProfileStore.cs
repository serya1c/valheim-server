using System.Text.Json;
using HearthLauncher.Engine;

namespace HearthLauncher;

public sealed class ProfileStore
{
    readonly string directory;
    readonly string file;
    static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    public ProfileStore(string? stateDirectory = null)
    {
        directory = Path.GetFullPath(stateDirectory ?? PlatformIntegration.DefaultStateDirectory);
        file = Path.Combine(directory, "profiles.json");
    }

    public LauncherSettings Load()
    {
        Installer.NoLinks(file);
        if (!File.Exists(file))
            return new("ru", [new("loki", "Loki", "https://loki.ach-play.ru", "")], "loki");
        if (new FileInfo(file).Length > 1024 * 1024) throw new IOException("Файл профилей слишком большой.");
        try
        {
            var settings = JsonSerializer.Deserialize<LauncherSettings>(File.ReadAllBytes(file))
                ?? throw new InvalidDataException("Файл профилей повреждён.");
            Validate(settings);
            return settings;
        }
        catch (JsonException error) { throw new InvalidDataException("Файл профилей повреждён.", error); }
    }

    public void Save(LauncherSettings settings)
    {
        Validate(settings);
        Installer.NoLinks(directory);
        Directory.CreateDirectory(directory);
        Installer.NoLinks(file);
        var bytes = JsonSerializer.SerializeToUtf8Bytes(settings, JsonOptions);
        if (bytes.Length > 1024 * 1024) throw new IOException("Файл профилей слишком большой.");
        string temporary = Path.Combine(directory, ".profiles-" + Guid.NewGuid().ToString("N"));
        try
        {
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { stream.Write(bytes); stream.Flush(true); }
            File.Move(temporary, file, true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    static void Validate(LauncherSettings settings)
    {
        if (settings.Language is not ("ru" or "en") || settings.Profiles is null || settings.Profiles.Count > 100)
            throw new InvalidDataException("Некорректные настройки лаунчера.");
        var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var profile in settings.Profiles)
        {
            if (profile is null || !Text(profile.Id, 100, false) || !ids.Add(profile.Id)
                || !Text(profile.Name, 200, false) || !Text(profile.GamePath, 4096, true)
                || !Text(profile.AddressOverride, 260, true))
                throw new InvalidDataException("Некорректный профиль сервера.");
            SourceClient.Endpoint(profile.Website);
            if (profile.AddressOverride.Length != 0) LauncherService.ValidateAddress(profile.AddressOverride);
        }
        if (settings.SelectedProfileId is not null && !ids.Contains(settings.SelectedProfileId))
            throw new InvalidDataException("Выбранный профиль сервера не найден.");
    }

    static bool Text(string? value, int maximum, bool empty) => value is not null
        && value.Length <= maximum && (empty || value.Trim().Length > 0) && !value.Any(char.IsControl);
}
