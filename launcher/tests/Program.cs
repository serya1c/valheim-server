using HearthLauncher.Tests;
using HearthLauncher.Engine;

if (args is ["--read-game-version", var game])
{
    Console.WriteLine(GameVersionReader.Read(game) ?? "Unknown");
    return;
}

await PlatformTests.RunAsync();
await GameVersionTests.RunAsync();
await ServiceTests.RunAsync();
Console.WriteLine("Hearth Launcher: all platform and synchronization scenarios passed.");
