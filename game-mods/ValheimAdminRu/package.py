"""Build the bundled plugin ZIP after build.ps1. Never package game assemblies."""
import hashlib
import json
from pathlib import Path
import re
import zipfile

root = Path(__file__).resolve().parent
repo = root.parents[1]
version = re.search(r'<Version>([^<]+)</Version>', (root / 'ValheimAdminRu.csproj').read_text()).group(1)
compatibility = (root / 'src/GameCompatibility.cs').read_text(encoding='utf-8')
games = re.findall(r'"([0-9]+\.[0-9]+\.[0-9]+)"',
                   re.search(r'SupportedVersions\s*=\s*\{([^}]+)\}', compatibility).group(1))
build_game = re.search(r'BuildVersion\s*=\s*"([^"]+)"', compatibility).group(1)
if not games or build_game not in games or len(games) != len(set(games)):
    raise SystemExit('Invalid supported game versions')
dll = root / 'bin/Release/net48/ValheimAdminRu.dll'
if not dll.is_file() or dll.read_bytes()[:2] != b'MZ':
    raise SystemExit('Build the plugin with build.ps1 first')
target = repo / 'app/builtin-mods/ValheimAdminRu.zip'
target.parent.mkdir(parents=True, exist_ok=True)
manifest = {'name': 'Hearth_Admin', 'version_number': version, 'dependencies': [],
            'description': 'Hearth in-game admin tools. Install on server and all clients. F8: RU / EN.'}
entries = {'BepInEx/plugins/ValheimAdminRu/ValheimAdminRu.dll': dll.read_bytes(),
           'manifest.json': (json.dumps(manifest, indent=2) + '\n').encode(),
           'README.md': ('Hearth Admin ' + version + '\n\nServer and all clients need the same version. '
                         'Open F8 for RU / EN. Web tools require Hearth. '\
                         'Source: https://github.com/serya1c/valheim-server/tree/main/game-mods/ValheimAdminRu\n').encode()}
with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for name, content in sorted(entries.items()):
        info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, content)
descriptor = {'id': 'Hearth-ValheimAdmin', 'version': version, 'games': games,
              'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
target.with_suffix('.json').write_text(json.dumps(descriptor, indent=2) + '\n', encoding='utf-8')
print(json.dumps(descriptor))
