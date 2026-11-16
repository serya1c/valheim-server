"""Читает и обновляет целевую версию Valheim у Hearth Admin.

Используется CI при выходе новой сборки игры: правит GameCompatibility.cs
(BuildVersion и allowlist) и бампает patch-версию мода в csproj.
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMPAT = ROOT / 'src/GameCompatibility.cs'
CSPROJ = ROOT / 'ValheimAdminRu.csproj'
MAX_VERSIONS = 6
VERSION = re.compile(r'^\d+\.\d+\.\d+$')


def read() -> str:
    match = re.search(r'BuildVersion\s*=\s*"([^"]+)"', COMPAT.read_text(encoding='utf-8'))
    if not match:
        raise SystemExit('BuildVersion не найден в GameCompatibility.cs')
    return match.group(1)


def versions() -> list:
    text = COMPAT.read_text(encoding='utf-8')
    block = re.search(r'SupportedVersions\s*=\s*\{([^}]+)\}', text)
    if not block:
        raise SystemExit('SupportedVersions не найден в GameCompatibility.cs')
    return re.findall(r'"([^"]+)"', block.group(1))


def mod_version() -> str:
    return re.search(r'<Version>([^<]+)</Version>', CSPROJ.read_text(encoding='utf-8')).group(1)


def bump_patch(version: str) -> str:
    major, minor, patch = (int(part) for part in version.split('.'))
    return f'{major}.{minor}.{patch + 1}'


def set_target(game: str) -> dict:
    if not VERSION.match(game):
        raise SystemExit(f'Некорректная версия игры: {game}')
    known = versions()
    if game in known:
        return {'game': game, 'mod': mod_version(), 'changed': False}

    updated = (known + [game])[-MAX_VERSIONS:]
    text = COMPAT.read_text(encoding='utf-8')
    text = re.sub(r'(BuildVersion\s*=\s*")[^"]+(")', lambda m: m.group(1) + game + m.group(2), text)
    text = re.sub(r'SupportedVersions\s*=\s*\{[^}]+\}',
                  'SupportedVersions = { ' + ', '.join(f'"{item}"' for item in updated) + ' }', text)
    COMPAT.write_text(text, encoding='utf-8')

    mod = bump_patch(mod_version())
    project = CSPROJ.read_text(encoding='utf-8')
    project = re.sub(r'<Version>[^<]+</Version>', f'<Version>{mod}</Version>', project, count=1)
    CSPROJ.write_text(project, encoding='utf-8')
    return {'game': game, 'mod': mod, 'changed': True, 'versions': updated}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--read', action='store_true', help='напечатать BuildVersion')
    group.add_argument('--get-supported', action='store_true', help='напечатать состояние как JSON')
    group.add_argument('--set', metavar='VERSION', help='перейти на версию игры и бампнуть мод')
    args = parser.parse_args()

    if args.read:
        print(read())
    elif args.get_supported:
        print(json.dumps({'build': read(), 'versions': versions(), 'mod': mod_version()}, ensure_ascii=False))
    else:
        print(json.dumps(set_target(args.set), ensure_ascii=False))


if __name__ == '__main__':
    main()
