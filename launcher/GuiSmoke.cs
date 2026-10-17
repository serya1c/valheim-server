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
        var otherPath = "/Steam/steamapps/common/Valheim-alt";
        var window = new MainWindow(service, new LauncherSettings(language, [profile], profile.Id), _ => { }, [profile.GamePath, otherPath], true);
        window.Show(); Dispatcher.UIThread.RunJobs();
        Complete(window.InspectionForSmoke);
        // Opened and deferred input notifications may both trigger inspection.
        // Assert the completed result rather than a platform-dependent event count.
        if (service.Calls < 1 || window.ReportForSmoke is null || window.CheckingForSmoke)
            throw new Exception($"Opening the launcher did not automatically inspect the saved selection (calls={service.Calls}, report={window.ReportForSmoke is not null}, checking={window.CheckingForSmoke})");
        window.PreviewReport(DemoService.Report());
        window.AssertSmoke(); Dispatcher.UIThread.RunJobs();
        foreach (var (state, key) in new[] { (ClientCollectionState.FolderRequired, "collectionFolder"), (ClientCollectionState.NotRequired, "collectionVanilla"), (ClientCollectionState.CheckFailed, "checkFailed") })
        {
            window.PreviewReport(DemoService.Report() with { ClientState = state, ClientCheckError = state == ClientCollectionState.CheckFailed ? "fixture: local check failed" : null });
            if (window.CollectionTextForSmoke != UiText.Get("ru", key) || window.ReportForSmoke?.Server.Game != "1.0.17")
                throw new Exception("Client check state lost its message or server metrics: " + state);
        }
        CheckAutomaticInspection(window, service, profile, otherPath);
        window.PreviewReport(DemoService.Report()); window.SetLanguage(language, false); Dispatcher.UIThread.RunJobs();
        if (service.Mutations != 0) throw new InvalidOperationException("Automatic checks changed files or started the game");
        if (args[0] == "--render-preview")
        {
            if (args.Length < 2) throw new ArgumentException("Usage: --render-preview PATH [ru|en]");
            using var frame = window.CaptureRenderedFrame() ?? throw new InvalidOperationException("Headless rendering returned no frame");
            frame.Save(Path.GetFullPath(args[1]), new PngBitmapEncoderOptions());
        }
        window.Close();
        Console.WriteLine("GUI smoke passed: RU/EN, drafts, folders, automatic read-only checks, debounce, stale-result/cancellation guards and busy controls.");
        return 0;
    }

    private static void Complete(Task task)
    {
        var until = DateTime.UtcNow.AddSeconds(10);
        while (!task.IsCompleted && DateTime.UtcNow < until)
        { Dispatcher.UIThread.RunJobs(); Thread.Sleep(5); }
        if (!task.IsCompleted) throw new TimeoutException("GUI fixture did not complete");
        task.GetAwaiter().GetResult(); Dispatcher.UIThread.RunJobs();
    }

    private static void CheckAutomaticInspection(MainWindow window, DemoService service, LauncherProfile profile, string otherPath)
    {
        // Selecting a second folder checks that folder, without a manual check button.
        window.SelectGameForSmoke(otherPath); Complete(window.InspectionForSmoke);
        if (service.LastProfile?.GamePath != otherPath || window.ReportForSmoke is null)
            throw new Exception("Folder selection did not inspect the selected directory");
        // Debouncing must send only the final website, not unfinished input.
        int calls = service.Calls;
        window.SetWebsiteForSmoke("unfinished"); window.SetWebsiteForSmoke("https://new.example");
        Complete(window.InspectionForSmoke);
        if (service.Calls != calls + 1 || service.LastProfile?.Website != "https://new.example")
            throw new Exception("Website checks were not debounced");
        // Simulate an HTTP handler that ignores cancellation and completes late.
        var held = service.HoldNext = new TaskCompletionSource<LauncherReport>();
        window.SelectGameForSmoke(profile.GamePath);
        var stale = window.InspectionForSmoke;
        var until = DateTime.UtcNow.AddSeconds(5);
        while (service.HoldNext is not null && DateTime.UtcNow < until)
        { Dispatcher.UIThread.RunJobs(); Thread.Sleep(5); }
        if (service.HoldNext is not null) throw new Exception("Held check did not start");
        window.SetWebsiteForSmoke("https://latest.example"); Complete(window.InspectionForSmoke);
        held.SetResult(DemoService.Report() with { Server = DemoService.Report().Server with { Title = "STALE" } });
        Complete(stale);
        if (window.ReportForSmoke?.Server.Title == "STALE" || window.ReportForSmoke?.Server.Website != "https://latest.example")
            throw new Exception("An old selection replaced the current server report");
        // A background failure must clear ready state, remain in the window and allow retry.
        service.FailNext = true;
        window.SelectGameForSmoke(otherPath); Complete(window.InspectionForSmoke);
        if (window.ReportForSmoke is not null || window.CollectionTextForSmoke != UiText.Get("ru", "checkFailed"))
            throw new Exception("A failed check retained a ready client status");
        window.SetLanguage("en", false);
        if (window.CollectionTextForSmoke != UiText.Get("en", "checkFailed")) throw new Exception("Check status was not translated");
        window.SetLanguage("ru", false);
        window.SelectGameForSmoke(profile.GamePath); Complete(window.InspectionForSmoke);
        window.SetWebsiteForSmoke("https://cancelled.example");
        var cancelled = window.InspectionForSmoke;
        calls = service.Calls; window.BeginOperationForSmoke(); Complete(cancelled); window.EndOperationForSmoke();
        if (service.Calls != calls || window.CheckingForSmoke) throw new Exception("A mutating action did not cancel a pending inspection");
        window.SetWebsiteForSmoke(profile.Website); Complete(window.InspectionForSmoke);
    }

    private sealed class DemoService : ILauncherService
    {
        public int Calls;
        public int Mutations;
        public LauncherProfile? LastProfile;
        public TaskCompletionSource<LauncherReport>? HoldNext;
        public bool FailNext;
        public event Action<string>? Log;
        public static LauncherReport Report() => new(new ServerSnapshot("Loki / Hearth Demo", "https://loki.example", "loki.example:2456", "1.0.17", null, "modded", true, 4, "https://community.example", ["Hearth Admin 0.4.0", "AzuAreaRepair 1.1.8 · Hexium"]), 0, 18, false, "1.0.17", [UiText.Get("ru", "protonNote")]);
        public Task<LauncherReport> InspectAsync(LauncherProfile profile, CancellationToken cancellationToken = default)
        {
            Calls++; LastProfile = profile; Log?.Invoke("Демонстрация");
            if (FailNext) { FailNext = false; throw new IOException("fixture: server unavailable"); }
            if (HoldNext is { } held) { HoldNext = null; return held.Task; }
            return Task.FromResult(Report() with { Server = Report().Server with { Website = profile.Website } });
        }
        public Task<LauncherReport> SynchronizeAsync(LauncherProfile profile, CancellationToken cancellationToken = default) { Mutations++; return Task.FromResult(Report()); }
        public Task RestoreAsync(LauncherProfile profile, CancellationToken cancellationToken = default) { Mutations++; return Task.CompletedTask; }
        public Task<LauncherReport> PlayAsync(LauncherProfile profile, bool connect, CancellationToken cancellationToken = default) { Mutations++; return Task.FromResult(Report()); }
    }
}
