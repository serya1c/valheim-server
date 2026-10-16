using System;

namespace ValheimAdminRu
{
    internal static class GameCompatibility
    {
        internal const string BuildVersion = "1.0.20";
        // package.py reads this same allowlist for the panel's bundled package.
        private static readonly string[] SupportedVersions = { "1.0.16", "1.0.17", "1.0.20" };
        internal static string SupportedVersionsText => string.Join(", ", SupportedVersions);
        internal static bool Supports(string version) => Array.IndexOf(SupportedVersions, version) >= 0;
    }
}
