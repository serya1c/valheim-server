using Avalonia.Headless;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using System.Text.RegularExpressions;

namespace HearthLauncher;

internal static class GuiSmoke
{
    public static int Run(string[] args)
    {
        var language = args.Length > 2 && args[2] == "en" ? "en" : "ru";
        foreach (var entry in UiText.Strings)
        {
            var ru = Regex.Matches(entry.Value.Ru, @"\{\d+\}").Select(m => m.Value);
            var en = Regex.Matches(entry.Value.En, @"\{\d+\}").Select(m => m.Value);
            if (string.IsNullOrWhiteSpace(entry.Value.En) || !ru.SequenceEqual(en)) throw new Exception("Locale placeholders differ: " + entry.Key);
        }
        const string literalPath = "C:/Steam/Игры/Valheim/plugin.dll";
        if (UiText.Translate("en", "Путь клиентского мода занят чужим файлом: " + literalPath + ". Сохраните его отдельно перед синхронизацией.")
            != "A client mod path is occupied by an unmanaged file: " + literalPath + ". Back it up separately before synchronizing.")
            throw new Exception("Translation changed a literal file path");
        var service = new DemoService();
        var profile = new LauncherProfile("demo", "Loki · demo", "https://loki.example", "/Steam/steamapps/common/Valheim");
        var window = new MainWindow(service, new LauncherSettings(language, [profile], profile.Id), _ => { }, [profile.GamePath], true);
        window.Show(); Dispatcher.UIThread.RunJobs();
        window.PreviewReport(DemoService.Report());
        window.AssertSmoke(); Dispatcher.UIThread.RunJobs();
        window.PreviewReport(DemoService.Report()); window.SetLanguage(language, false); Dispatcher.UIThread.RunJobs();
        if (service.Calls != 0) throw new InvalidOperationException("Opening the UI performed a service operation");
        if (args[0] == "--render-preview")
        {
            if (args.Length < 2) throw new ArgumentException("Usage: --render-preview PATH [ru|en]");
            using var frame = window.CaptureRenderedFrame() ?? throw new InvalidOperationException("Headless rendering returned no frame");
            frame.Save(Path.GetFullPath(args[1]), new PngBitmapEncoderOptions());
        }
        window.Close();
        Console.WriteLine("GUI smoke passed: RU/EN placeholders, literal paths, unsaved drafts, published/override addresses, busy guard, no service calls on startup.");
        return 0;
    }

    private sealed class DemoService : ILauncherService
    {
        public int Calls;
        public event Action<string>? Log;
        public static LauncherReport Report() => new(new ServerSnapshot("Loki / Hearth Demo", "https://loki.example", "loki.example:2456", "1.0.17", null, "modded", true, 4, "https://community.example", ["Hearth Admin 0.4.0", "AzuAreaRepair 1.1.8 · Hexium"]), 0, 18, false, null, [UiText.Get("ru", "protonNote")]);
        public Task<LauncherReport> InspectAsync(LauncherProfile profile, CancellationToken cancellationToken = default) { Calls++; Log?.Invoke("Демонстрация"); return Task.FromResult(Report()); }
        public Task<LauncherReport> SynchronizeAsync(LauncherProfile profile, CancellationToken cancellationToken = default) { Calls++; return Task.FromResult(Report()); }
        public Task RestoreAsync(LauncherProfile profile, CancellationToken cancellationToken = default) { Calls++; return Task.CompletedTask; }
        public Task PlayAsync(LauncherProfile profile, bool connect, CancellationToken cancellationToken = default) { Calls++; return Task.CompletedTask; }
    }
}
