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
for runtime in win-x64 linux-x64; do
  "$dotnet_bin" publish "$launcher_dir/HearthLauncher.csproj" -c Release -r "$runtime" --self-contained true --no-restore -o "$build_dir/publish/$runtime"
done
"$python_bin" "$launcher_dir/package.py"
printf 'Launcher assets: %s/assets\n' "$build_dir"
