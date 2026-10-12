using HearthLauncher.Tests;

await PlatformTests.RunAsync();
await ServiceTests.RunAsync();
Console.WriteLine("Hearth Launcher: all platform and synchronization scenarios passed.");
