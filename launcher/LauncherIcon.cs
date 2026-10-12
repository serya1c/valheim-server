using Avalonia.Controls;
using Avalonia.Platform;

namespace HearthLauncher;

public static class LauncherIcon
{
    public static WindowIcon Load()
    {
        using var resource = AssetLoader.Open(new Uri("avares://HearthLauncher/Assets/hearth.png"));
        return new WindowIcon(resource);
    }
}
