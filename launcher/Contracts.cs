namespace HearthLauncher;

public record LauncherProfile(string Id, string Name, string Website, string GamePath, string AddressOverride = "");
public record LauncherSettings(string Language, List<LauncherProfile> Profiles, string? SelectedProfileId);
public record ServerSnapshot(string Title, string Website, string Address, string Game, string? Mod,
    string Mode, bool Running, int? Players, string? CommunityUrl, IReadOnlyList<string> Packages);
public enum ClientCollectionState { FolderRequired, InstallRequired, UpdateRequired, Ready, NotRequired, CheckFailed }
public record LauncherReport(ServerSnapshot Server, int ChangedFiles, int TotalFiles, bool NeedsSync,
    string? LocalGameVersion, IReadOnlyList<string> Notes)
{
    public ClientCollectionState ClientState { get; init; } = NeedsSync ? ClientCollectionState.UpdateRequired : ClientCollectionState.Ready;
    public string? ClientCheckError { get; init; }
}

public interface ILauncherService
{
    event Action<string>? Log;
    Task<LauncherReport> InspectAsync(LauncherProfile profile, CancellationToken cancellationToken = default);
    Task<LauncherReport> SynchronizeAsync(LauncherProfile profile, CancellationToken cancellationToken = default);
    Task RestoreAsync(LauncherProfile profile, CancellationToken cancellationToken = default);
    Task<LauncherReport> PlayAsync(LauncherProfile profile, bool connect, CancellationToken cancellationToken = default);
}
