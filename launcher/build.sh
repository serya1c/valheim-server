#!/usr/bin/env bash
set -euo pipefail
launcher_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
build_dir="$launcher_dir/.build"
export DOTNET_CLI_HOME="$build_dir/dotnet-home"
export NUGET_PACKAGES="$launcher_dir/.packages"
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export DOTNET_GENERATE_ASPNET_CERTIFICATE=false
dotnet_bin="${DOTNET:-dotnet}"
python_bin="${PYTHON:-python3}"
"$dotnet_bin" restore "$launcher_dir/HearthLauncher.csproj" --configfile "$launcher_dir/NuGet.Config" --locked-mode -p:SelfContained=true
"$dotnet_bin" build "$launcher_dir/HearthLauncher.csproj" -c Release --no-restore
"$dotnet_bin" "$launcher_dir/bin/Release/net10.0/HearthLauncher.dll" --smoke-test
"$dotnet_bin" restore "$launcher_dir/setup-tests/Setup.Tests.csproj" --configfile "$launcher_dir/NuGet.Config"
"$dotnet_bin" run --project "$launcher_dir/setup-tests/Setup.Tests.csproj" -c Release --no-restore
for runtime in win-x64 linux-x64; do
  "$dotnet_bin" publish "$launcher_dir/HearthLauncher.csproj" -c Release -r "$runtime" --self-contained true --no-restore -o "$build_dir/publish/$runtime"
done
"$python_bin" "$launcher_dir/package.py" --prepare-setup
"$dotnet_bin" restore "$launcher_dir/setup/HearthLauncherSetup.csproj" --configfile "$launcher_dir/NuGet.Config" --locked-mode
"$dotnet_bin" publish "$launcher_dir/setup/HearthLauncherSetup.csproj" -c Release --no-restore -o "$build_dir/publish/setup-win-x64"
"$python_bin" "$launcher_dir/package.py"
printf 'Launcher assets: %s/assets\n' "$build_dir"
