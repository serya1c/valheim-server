using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input.Platform;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Platform.Storage;
using Avalonia.Threading;

namespace HearthLauncher;

public sealed class MainWindow : Window
{
    private static readonly IBrush BackgroundInk = Brush.Parse("#101A15");
    private static readonly IBrush PanelInk = Brush.Parse("#19271F");
    private static readonly IBrush Line = Brush.Parse("#34483B");
    private static readonly IBrush Gold = Brush.Parse("#E7BE76");
    private static readonly IBrush Muted = Brush.Parse("#A9B5A8");
    private readonly ILauncherService _service;
    private readonly Action<LauncherSettings> _save;
    private readonly List<LauncherProfile> _profiles;
    private readonly List<Action> _translations = [];
    private readonly List<Control> _blocked = [];
    private readonly List<(DateTime At, string Text)> _logs = [];
    private readonly ComboBox _profile = new() { HorizontalAlignment = HorizontalAlignment.Stretch };
    private readonly ComboBox _detected = new() { HorizontalAlignment = HorizontalAlignment.Stretch };
    private readonly TextBox _name = Input();
    private readonly TextBox _website = Input();
    private readonly TextBox _folder = Input();
    private readonly TextBox _address = Input();
    private readonly TextBlock _serverTitle = new() { FontSize = 29, FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _status = new() { Foreground = Gold, FontSize = 15, TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _details = new() { Foreground = Muted, TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _serverGame = Value();
    private readonly TextBlock _localGame = Value();
    private readonly TextBlock _mod = Value();
    private readonly TextBlock _online = Value();
    private readonly TextBlock _packages = new() { Foreground = Muted, TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _notes = new() { TextWrapping = TextWrapping.Wrap, Foreground = Muted };
    private readonly TextBox _activity = new() { IsReadOnly = true, AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, MinHeight = 112, MaxHeight = 180, Background = BackgroundInk, FontSize = 12 };
    private readonly CheckBox _connect = new() { IsChecked = true };
    private readonly ProgressBar _progress = new() { Height = 4, IsIndeterminate = true, IsVisible = false, Foreground = Gold };
    private readonly Button _ru = new() { Content = "RU", MinWidth = 44 };
    private readonly Button _en = new() { Content = "EN", MinWidth = 44 };
    private readonly Button _cancel;
    private readonly Button _community;
    private readonly Button _copyAddress;
    private readonly Border _proton;
    private readonly bool _showProton;
    private LauncherSettings _persisted;
    private string _language;
    private string? _selectedId;
    private LauncherReport? _report;
    private CancellationTokenSource? _operation;
    private bool _busy, _changingProfiles;
    private string _statusKey = "notChecked";

    public MainWindow(ILauncherService service, LauncherSettings settings, Action<LauncherSettings> save,
        IReadOnlyList<string>? detectedGames = null, bool showProton = false)
    {
        _service = service;
        _save = save;
        _persisted = settings with { Profiles = settings.Profiles.ToList() };
        _showProton = showProton || OperatingSystem.IsLinux();
        _language = settings.Language == "en" ? "en" : "ru";
        _profiles = settings.Profiles.ToList();
        if (_profiles.Count == 0) _profiles.Add(new LauncherProfile(Guid.NewGuid().ToString("N"), "Loki", "https://loki.ach-play.ru", ""));
        _selectedId = _profiles.Any(p => p.Id == settings.SelectedProfileId) ? settings.SelectedProfileId : _profiles[0].Id;
        Title = "Hearth Launcher";
        Width = 1170; Height = 870; MinWidth = 920; MinHeight = 680;
        Background = BackgroundInk;
        Foreground = Brush.Parse("#E9EEE6");
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        FontFamily = new FontFamily("Segoe UI, DejaVu Sans, sans-serif");
        FontSize = 13;

        var add = Button("new", () => { CaptureDraft(); _profiles.Add(new LauncherProfile(Guid.NewGuid().ToString("N"), T("newName"), "", _folder.Text ?? "")); _selectedId = _profiles[^1].Id; RefreshProfiles(); LoadProfile(); });
        var delete = Button("delete", DeleteProfileAsync);
        var saveButton = Button("save", SaveProfile);
        var detect = Button("find", DetectGames);
        var browse = Button("browse", BrowseAsync);
        var check = Button("check", () => RunAsync("checked", async p => await _service.InspectAsync(p, Token)));
        var sync = Button("sync", SynchronizeAsync);
        var restore = Button("restore", RestoreAsync);
        var play = Button("play", PlayAsync, true);
        play.FontSize = 21; play.MinHeight = 54; play.MinWidth = 180;
        _cancel = Button("cancel", () => _operation?.Cancel(), block: false); _cancel.IsEnabled = false;
        _community = Button("community", () => OpenLinkAsync(_report?.Server.CommunityUrl), block: false);
        _community.IsVisible = false;
        var website = Button("websiteButton", () => OpenLinkAsync(_website.Text), block: false);
        var clear = Button("clear", () => { _logs.Clear(); RenderLogs(); }, block: false);
        _copyAddress = Button("copyAddress", CopyAddressAsync, block: false);
        _ru.Click += (_, _) => SetLanguage("ru"); _en.Click += (_, _) => SetLanguage("en");
        _translations.Add(() => _connect.Content = T("connect"));

        _profile.SelectionChanged += (_, _) =>
        {
            if (_changingProfiles || _busy || _profile.SelectedItem is not ProfileChoice selected) return;
            CaptureDraft(); _selectedId = selected.Id; LoadProfile();
        };
        _detected.SelectionChanged += (_, _) => { if (!_busy && _detected.SelectedItem is string path) _folder.Text = path; };
        foreach (var field in new Control[] { _profile, _detected, _name, _website, _folder, _address, _connect }) _blocked.Add(field);

        var identity = new StackPanel { Spacing = 8 };
        identity.Children.Add(new TextBlock { Text = "ᛟ  H E A R T H", Foreground = Gold, FontSize = 25, FontWeight = FontWeight.SemiBold });
        identity.Children.Add(Text("subtitle", 10, Gold));
        identity.Children.Add(new StackPanel { Orientation = Orientation.Horizontal, Spacing = 5, Margin = new Thickness(0, 8, 0, 16), Children = { _ru, _en } });
        identity.Children.Add(Text("profiles", 18));
        identity.Children.Add(_profile);
        identity.Children.Add(Row(add, delete));
        identity.Children.Add(Field("name", _name));
        identity.Children.Add(Field("website", _website, "websiteHint"));
        identity.Children.Add(Field("gameFolder", _folder));
        identity.Children.Add(Text("detected", 11, Muted));
        identity.Children.Add(_detected);
        identity.Children.Add(Row(detect, browse));
        identity.Children.Add(Field("endpoint", _address, "endpointHint"));
        identity.Children.Add(saveButton);
        identity.Children.Add(new TextBlock { Text = "HEARTH LAUNCHER · 1.0.0", FontSize = 10, Foreground = Muted, Margin = new Thickness(0, 20, 0, 0) });
        var sidebar = new Border { Background = PanelInk, BorderBrush = Line, BorderThickness = new Thickness(0, 0, 1, 0), Padding = new Thickness(24), Child = new ScrollViewer { Content = identity } };

        var body = new StackPanel { Spacing = 16, Margin = new Thickness(28, 24) };
        body.Children.Add(new DockPanel { Children = { _serverTitle, new TextBlock { Text = "VALHEIM / STEAM", Foreground = Gold, FontSize = 10, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(12, 12) } } });
        body.Children.Add(Text("intro", 13, Muted));
        body.Children.Add(Card(new StackPanel { Spacing = 9, Children = { _status, _details, _progress } }));
        var metrics = new Grid { ColumnDefinitions = new ColumnDefinitions("*,*,*,*"), ColumnSpacing = 10 };
        AddGrid(metrics, Metric("serverGame", _serverGame), 0); AddGrid(metrics, Metric("clientGame", _localGame), 1);
        AddGrid(metrics, Metric("mod", _mod), 2); AddGrid(metrics, Metric("online", _online), 3);
        body.Children.Add(metrics);
        var actions = new StackPanel { Spacing = 10 };
        actions.Children.Add(Row(_connect, _copyAddress));
        actions.Children.Add(Text("playHint", 11, Muted));
        actions.Children.Add(Row(play, check, sync));
        actions.Children.Add(Row(restore, _cancel, website, _community));
        body.Children.Add(actions);
        body.Children.Add(Card(new StackPanel { Spacing = 9, Children = { Text("packages", 16), _packages, Text("notes", 12, Gold), _notes } }));
        var protonBody = new StackPanel { Spacing = 8, Children = { Text("protonTitle", 15), Text("protonBody", 12, Muted),
            new TextBlock { Text = "WINEDLLOVERRIDES=\"winhttp=n,b\" %command%", FontFamily = FontFamily.Default, Foreground = Gold, TextWrapping = TextWrapping.Wrap },
            Button("copyProton", CopyProtonAsync, block: false) } };
        _proton = Card(protonBody); _proton.IsVisible = _showProton; body.Children.Add(_proton);
        clear.Margin = new Thickness(14, 0, 0, 0);
        body.Children.Add(new DockPanel { LastChildFill = false, Children = { Text("log", 16), clear } });
        body.Children.Add(_activity);
        var main = new Grid { ColumnDefinitions = new ColumnDefinitions("330,*") };
        main.Children.Add(sidebar); AddGrid(main, new ScrollViewer { Content = body }, 1);
        Content = main;

        _service.Log += OnServiceLog;
        Closing += (_, eventArgs) =>
        {
            if (!_busy) return;
            eventArgs.Cancel = true;
            _ = ShowErrorAsync(T("busyClose"));
        };
        Closed += (_, _) => _service.Log -= OnServiceLog;
        foreach (var input in new[] { _website, _folder, _address }) input.TextChanged += (_, _) =>
        { if (!_busy) { _report = null; _statusKey = "notChecked"; RenderReport(); } };
        RefreshProfiles(); LoadProfile();
        SetDetected(detectedGames ?? SafeFindGames());
        var matching = (_detected.ItemsSource as IReadOnlyList<string>)?.FirstOrDefault(path => path == _folder.Text);
        if (matching is not null) _detected.SelectedItem = matching;
        if (string.IsNullOrWhiteSpace(_folder.Text) && _detected.ItemCount > 0) _detected.SelectedIndex = 0;
        UpdateLanguage();
    }

    private string T(string key, params object[] args) => UiText.Get(_language, key, args);
    private CancellationToken Token => _operation?.Token ?? CancellationToken.None;
    private static TextBox Input() => new() { MinHeight = 38, Background = BackgroundInk, BorderBrush = Line, CornerRadius = new CornerRadius(6) };
    private static TextBlock Value() => new() { Text = "—", FontSize = 17, FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap };
    private TextBlock Text(string key, double size = 13, IBrush? color = null)
    {
        var text = new TextBlock { FontSize = size, Foreground = color ?? Foreground, TextWrapping = TextWrapping.Wrap };
        _translations.Add(() => text.Text = T(key)); return text;
    }
    private Button Button(string key, Action action, bool primary = false, bool block = true) => Button(key, () => { action(); return Task.CompletedTask; }, primary, block);
    private Button Button(string key, Func<Task> action, bool primary = false, bool block = true)
    {
        var button = new Button { Padding = new Thickness(13, 10), MinHeight = 38, CornerRadius = new CornerRadius(7),
            Background = primary ? Gold : PanelInk, Foreground = primary ? BackgroundInk : Foreground, BorderBrush = Line, BorderThickness = new Thickness(1) };
        _translations.Add(() => button.Content = T(key));
        button.Click += async (_, _) => { try { await action(); } catch (Exception error) { await ShowErrorAsync(error.Message); } };
        if (block) _blocked.Add(button);
        return button;
    }
    private static WrapPanel Row(params Control[] controls)
    {
        var row = new WrapPanel();
        foreach (var control in controls) { control.Margin = new Thickness(0, 0, 8, 7); row.Children.Add(control); }
        return row;
    }
    private StackPanel Field(string label, TextBox input, string? hint = null)
    {
        var field = new StackPanel { Spacing = 5, Margin = new Thickness(0, 5, 0, 0), Children = { Text(label, 12, Muted), input } };
        if (hint is not null) field.Children.Add(Text(hint, 10, Muted));
        return field;
    }
    private static Border Card(Control content) => new() { Background = PanelInk, BorderBrush = Line, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(12), Padding = new Thickness(16), Child = content };
    private Border Metric(string label, TextBlock value) => Card(new StackPanel { Spacing = 8, Children = { Text(label, 11, Muted), value } });
    private static void AddGrid(Grid grid, Control control, int column) { Grid.SetColumn(control, column); grid.Children.Add(control); }

    private void UpdateLanguage()
    {
        foreach (var translate in _translations) translate();
        _ru.Background = _language == "ru" ? Gold : PanelInk; _ru.Foreground = _language == "ru" ? BackgroundInk : Foreground;
        _en.Background = _language == "en" ? Gold : PanelInk; _en.Foreground = _language == "en" ? BackgroundInk : Foreground;
        RenderReport(); RenderLogs();
    }
    internal void SetLanguage(string language, bool persist = true)
    {
        _language = language == "en" ? "en" : "ru";
        UpdateLanguage();
        if (persist) { try { Persist(_persisted with { Language = _language }); } catch (Exception error) { _ = ShowErrorAsync(error.Message); } }
    }
    private void Persist(LauncherSettings settings) { _save(settings); _persisted = settings; }
    private void RefreshProfiles()
    {
        _changingProfiles = true;
        _profile.ItemsSource = _profiles.Select(p => new ProfileChoice(p.Id, p.Name)).ToList();
        _profile.SelectedIndex = _profiles.FindIndex(p => p.Id == _selectedId);
        _changingProfiles = false;
    }
    private void LoadProfile()
    {
        var profile = _profiles.First(p => p.Id == _selectedId);
        _name.Text = profile.Name; _website.Text = profile.Website; _folder.Text = profile.GamePath; _address.Text = profile.AddressOverride;
        _report = null; _statusKey = "notChecked"; RenderReport();
    }
    private LauncherProfile Draft(bool validate = false)
    {
        var name = (_name.Text ?? "").Trim(); var website = (_website.Text ?? "").Trim().TrimEnd('/');
        if (validate)
        {
            if (name.Length is < 1 or > 80) throw new InvalidOperationException(T("invalidName"));
            if (!Uri.TryCreate(website, UriKind.Absolute, out var uri) || uri.Scheme != "https" || uri.Port != 443 || uri.UserInfo.Length > 0 || uri.AbsolutePath != "/" || uri.Query.Length > 0 || uri.Fragment.Length > 0) throw new InvalidOperationException(T("invalidWebsite"));
        }
        return new LauncherProfile(_selectedId!, name, website, (_folder.Text ?? "").Trim(), (_address.Text ?? "").Trim());
    }
    private void CaptureDraft()
    {
        var index = _profiles.FindIndex(p => p.Id == _selectedId);
        if (index >= 0) _profiles[index] = Draft();
    }
    private void SaveProfile()
    {
        var profile = Draft(true); var index = _profiles.FindIndex(p => p.Id == profile.Id); _profiles[index] = profile;
        var saved = _persisted.Profiles.Where(p => p.Id != profile.Id).ToList(); saved.Add(profile);
        Persist(new LauncherSettings(_language, saved, profile.Id));
        RefreshProfiles(); AppendLog(UiText.Get("ru", "saved")); _serverTitle.Text = profile.Name;
    }
    private async Task DeleteProfileAsync()
    {
        if (!await ConfirmAsync("deleteTitle", "deleteBody", _name.Text ?? "")) return;
        _profiles.RemoveAll(p => p.Id == _selectedId);
        if (_profiles.Count == 0) _profiles.Add(new LauncherProfile(Guid.NewGuid().ToString("N"), T("newName"), "", ""));
        _selectedId = _profiles[0].Id;
        var saved = _persisted.Profiles.Where(p => _profiles.Any(draft => draft.Id == p.Id)).ToList();
        // The remaining selected draft may not have been saved yet.
        var selected = saved.Any(p => p.Id == _selectedId) ? _selectedId : saved.FirstOrDefault()?.Id;
        Persist(new LauncherSettings(_language, saved, selected)); RefreshProfiles(); LoadProfile();
    }
    private static IReadOnlyList<string> SafeFindGames()
    {
        try { return PlatformIntegration.FindGames(); } catch { return []; }
    }
    private void SetDetected(IReadOnlyList<string> games) => _detected.ItemsSource = games.ToList();
    private void DetectGames()
    {
        var games = SafeFindGames(); SetDetected(games);
        if (games.Count > 0) _detected.SelectedIndex = 0; else AppendLog(UiText.Get("ru", "notFound"));
    }
    private async Task BrowseAsync()
    {
        if (!StorageProvider.CanPickFolder) return;
        var folders = await StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions { Title = T("gameFolder"), AllowMultiple = false });
        if (folders.Count > 0) _folder.Text = folders[0].TryGetLocalPath() ?? _folder.Text;
    }

    private async Task SynchronizeAsync()
    {
        Draft(true);
        if (await ConfirmAsync("syncTitle", "syncBody", _name.Text ?? ""))
            await RunAsync("synced", async profile => await _service.SynchronizeAsync(profile, Token));
    }
    private async Task RestoreAsync()
    {
        Draft(true);
        if (!await ConfirmAsync("restoreTitle", "restoreBody", _name.Text ?? "")) return;
        await RunAsync("restored", async profile => { await _service.RestoreAsync(profile, Token); return null; });
    }
    private async Task PlayAsync()
    {
        var connect = _connect.IsChecked == true;
        await RunAsync("launched", async profile => { await _service.PlayAsync(profile, connect, Token); return null; });
    }
    private async Task RunAsync(string resultKey, Func<LauncherProfile, Task<LauncherReport?>> action)
    {
        if (_busy) return;
        var profile = Draft(true);
        if (string.IsNullOrWhiteSpace(profile.GamePath) || !Directory.Exists(profile.GamePath)) throw new InvalidOperationException(T("invalidFolder"));
        CaptureDraft(); SetBusy(true); _operation = new CancellationTokenSource();
        try
        {
            var result = await Task.Run(() => action(profile));
            _report = result ?? (resultKey == "restored" ? null : _report);
            _statusKey = resultKey; AppendLog(UiText.Get("ru", resultKey));
        }
        catch (OperationCanceledException) { _statusKey = "cancelled"; AppendLog(UiText.Get("ru", "cancelled")); }
        catch (Exception error) { AppendLog(error.Message); await ShowErrorAsync(error.Message); }
        finally { _operation.Dispose(); _operation = null; SetBusy(false); RenderReport(); }
    }
    private void SetBusy(bool value)
    {
        _busy = value;
        foreach (var control in _blocked) control.IsEnabled = !value;
        _cancel.IsEnabled = value; _progress.IsVisible = value; RenderReport();
    }
    internal void PreviewReport(LauncherReport report) { _report = report; _statusKey = "checked"; RenderReport(); }
    private void RenderReport()
    {
        _serverTitle.Text = _report?.Server.Title ?? (_name.Text?.Length > 0 ? _name.Text : T("welcome"));
        _status.Text = _busy ? T("working") : _report is not null && _statusKey is "checked" or "synced"
            ? T(_report.NeedsSync ? "needsSync" : _report.LocalGameVersion is null ? "unverified" : "ready") : T(_statusKey);
        _details.Text = _report is null ? T("idleHint") : T("changed", _report.ChangedFiles, _report.TotalFiles);
        _serverGame.Text = _report?.Server.Game ?? "—";
        _localGame.Text = _report?.LocalGameVersion ?? T("unknown");
        _mod.Text = _report is null ? "—" : _report.Server.Mode == "vanilla" ? T("vanilla") : _report.Server.Mode == "plus" ? "V+ " + (_report.Server.Mod ?? "—") : T("modded");
        _online.Text = _report is null ? "—" : !_report.Server.Running ? T("stopped") : _report.Server.Players?.ToString() ?? T("unknownPlayers");
        _packages.Text = _report?.Server.Packages.Count > 0 ? string.Join("\n", _report.Server.Packages.Select(p => "• " + p)) : T("noPackages");
        var notes = _report?.Notes.ToList() ?? [];
        if (_report is not null && _report.LocalGameVersion is null) notes.Add(UiText.Get("ru", "unknownVersionNote"));
        _notes.Text = notes.Count == 0 ? T("idleHint") : string.Join("\n", notes.Distinct().Select(note => "• " + UiText.Translate(_language, note)));
        _community.IsVisible = SafeUrl(_report?.Server.CommunityUrl, true);
        _proton.IsVisible = _showProton && _report?.Server.Mode != "vanilla";
        _copyAddress.IsEnabled = !string.IsNullOrWhiteSpace(ConnectionAddress());
    }
    private void OnServiceLog(string message) => Dispatcher.UIThread.Post(() => AppendLog(message));
    private void AppendLog(string source) { _logs.Add((DateTime.Now, source)); if (_logs.Count > 300) _logs.RemoveAt(0); RenderLogs(); }
    private void RenderLogs() => _activity.Text = string.Join("\n", _logs.Select(entry => $"{entry.At:HH:mm:ss}  {UiText.Translate(_language, entry.Text)}"));
    private static bool SafeUrl(string? text, bool community = false) => Uri.TryCreate(text, UriKind.Absolute, out var uri) &&
        (uri.Scheme == "https" || community && uri.Scheme == "http") && uri.UserInfo.Length == 0;
    private async Task OpenLinkAsync(string? text)
    {
        if (!SafeUrl(text, true)) { await ShowErrorAsync(T("invalidWebsite")); return; }
        PlatformIntegration.OpenUrl(text!);
    }
    private async Task CopyProtonAsync()
    {
        if (Clipboard is not null) { await Clipboard.SetTextAsync("WINEDLLOVERRIDES=\"winhttp=n,b\" %command%"); AppendLog(UiText.Get("ru", "copied")); }
    }
    private string? ConnectionAddress() => string.IsNullOrWhiteSpace(_address.Text) ? _report?.Server.Address : _address.Text.Trim();
    private async Task CopyAddressAsync()
    {
        var address = PlatformIntegration.NormalizeAddress(ConnectionAddress() ?? "");
        if (address.Length == 0) { await ShowErrorAsync(T("missingAddress")); return; }
        if (Clipboard is null) { await ShowErrorAsync(T("clipboardUnavailable")); return; }
        await Clipboard.SetTextAsync(address);
        AppendLog(UiText.Get("ru", "addressCopied") + address);
    }
    public async Task ShowErrorAsync(string source)
    {
        var content = new StackPanel { Spacing = 18, Margin = new Thickness(24) };
        content.Children.Add(new TextBlock { Text = UiText.Translate(_language, source), TextWrapping = TextWrapping.Wrap });
        content.Children.Add(new TextBlock { Text = T("errorFallback"), TextWrapping = TextWrapping.Wrap, Foreground = Muted });
        var window = Dialog(T("errorTitle"), content);
        var close = new Button { Content = T("close"), HorizontalAlignment = HorizontalAlignment.Right };
        close.Click += (_, _) => window.Close(); content.Children.Add(close); await window.ShowDialog(this);
    }
    private async Task<bool> ConfirmAsync(string title, string body, string identity)
    {
        var content = new StackPanel { Spacing = 16, Margin = new Thickness(24), Children = {
            new TextBlock { Text = identity, Foreground = Gold, FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap },
            new TextBlock { Text = T(body), TextWrapping = TextWrapping.Wrap } } };
        var window = Dialog(T(title), content);
        var cancel = new Button { Content = T("cancel") }; var accept = new Button { Content = T("continue"), Background = Gold, Foreground = BackgroundInk };
        cancel.Click += (_, _) => window.Close(false); accept.Click += (_, _) => window.Close(true);
        content.Children.Add(Row(cancel, accept)); return await window.ShowDialog<bool>(this);
    }
    private static Window Dialog(string title, Control content) => new() { Title = title, Width = 500, SizeToContent = SizeToContent.Height,
        CanResize = false, WindowStartupLocation = WindowStartupLocation.CenterOwner, Background = PanelInk,
        Foreground = Brush.Parse("#E9EEE6"), Content = content };

    internal void AssertSmoke()
    {
        var before = _website.Text;
        var originalReport = _report ?? throw new Exception("Smoke fixture requires a report");
        var persistedProfile = _persisted.Profiles.First(p => p.Id == _selectedId);
        _website.Text = "unfinished draft";
        SetLanguage("en");
        if (_persisted.Profiles.First(p => p.Id == persistedProfile.Id) != persistedProfile || _website.Text != "unfinished draft")
            throw new Exception("Changing language saved or discarded an unfinished profile draft");
        _website.Text = before; SetLanguage("en", false);
        if (!Equals(_connect.Content, UiText.Get("en", "connect")) || _website.Text != before) throw new Exception("Language switch did not preserve profile input");
        SetBusy(true);
        if (_profile.IsEnabled || _name.IsEnabled || !_cancel.IsEnabled || !_progress.IsVisible) throw new Exception("Busy guard is incomplete");
        SetBusy(false); SetLanguage("ru", false);
        if (!Equals(_connect.Content, UiText.Get("ru", "connect"))) throw new Exception("Language switch is not reversible");
        _address.Text = "override.example:2457";
        if (ConnectionAddress() != "override.example:2457") throw new Exception("Connection override was not preserved");
        _address.Text = "";
        PreviewReport(originalReport);
        if (ConnectionAddress() != _report?.Server.Address || !_copyAddress.IsEnabled) throw new Exception("Published game address was not offered for copying");
    }
    private sealed record ProfileChoice(string Id, string Name) { public override string ToString() => Name; }
}
