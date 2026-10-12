using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Media;
using Avalonia.Styling;
using Avalonia.Themes.Fluent;

namespace HearthLauncher;

public sealed class App : Application
{
    public override void Initialize()
    {
        RequestedThemeVariant = ThemeVariant.Dark;
        var theme = new FluentTheme();
        theme.Palettes[ThemeVariant.Dark] = new ColorPaletteResources
        {
            Accent = Color.Parse("#E7BE76"), RegionColor = Color.Parse("#15211B"),
            BaseHigh = Color.Parse("#E8EEE6"), BaseLow = Color.Parse("#33483A"),
        };
        Styles.Add(theme);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            var store = new ProfileStore();
            LauncherSettings settings;
            string? failure = null;
            try { settings = store.Load(); }
            catch (Exception error)
            {
                settings = new LauncherSettings("ru", [], null);
                failure = error.Message;
            }
            var window = new MainWindow(new LauncherService(), settings, store.Save);
            desktop.MainWindow = window;
            if (failure is not null) window.Opened += async (_, _) => await window.ShowErrorAsync(failure);
        }
        base.OnFrameworkInitializationCompleted();
    }
}
