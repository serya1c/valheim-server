using Avalonia;
using Avalonia.Headless;

namespace HearthLauncher;

internal static class Program
{
    [STAThread]
    public static int Main(string[] args)
    {
        if (args.Length > 0 && args[0] is "--smoke-test" or "--render-preview")
        {
            BuildHeadlessApp().SetupWithoutStarting();
            return GuiSmoke.Run(args);
        }
        return BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
    }

    public static AppBuilder BuildAvaloniaApp() => AppBuilder.Configure<App>().UsePlatformDetect();
    private static AppBuilder BuildHeadlessApp() => AppBuilder.Configure<App>().UseSkia()
        .UseHeadless(new AvaloniaHeadlessPlatformOptions { UseHeadlessDrawing = false });
}
