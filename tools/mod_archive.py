"""Решает, нужен ли PR после пересборки встроенного Hearth Admin.

Ночная пересборка DLL даёт другие байты при том же исходном коде: компилятор
не гарантирует побитовую воспроизводимость между запусками. Такой дрейф не
повод открывать PR, иначе бот присылает «свежую сборку архива» каждый день.

Сравнивается смысл, а не байты: версия мода, allowlist версий игры и отпечаток
исходников (`source` в описателе, его пишет package.py). Отдельно проверяется,
что закоммиченный описатель соответствует своему архиву.

Вывод: "true" или "false" в stdout, причина — в stderr.
Код возврата: 0 — PR нужен, 1 — нет.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = 'app/builtin-mods/ValheimAdminRu.json'
ARCHIVE = 'app/builtin-mods/ValheimAdminRu.zip'


def needs_commit(built, committed, committed_archive_sha, refresh=False):
    """Чистая функция: нужен ли коммит с пересобранным архивом."""
    if refresh:
        return True, 'изменилась сборка игры'
    if built.get('version') != committed.get('version'):
        return True, f"версия мода {committed.get('version')} → {built.get('version')}"
    if built.get('games') != committed.get('games'):
        return True, 'изменился allowlist версий игры'
    if built.get('source') != committed.get('source'):
        return True, 'изменились исходники мода'
    if committed.get('sha256') != committed_archive_sha:
        return True, 'описатель не совпадает с закоммиченным архивом'
    return False, 'отличаются только байты сборки: версия, allowlist и исходники прежние'


def git(*args):
    """Сырой вывод команды git как bytes."""
    return subprocess.run(['git', '-C', str(ROOT), *args], capture_output=True, check=True).stdout


def git_text(*args):
    return git(*args).decode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', default='false', choices=['true', 'false'],
                        help='steps.target.outputs.refresh: сменилась ли сборка игры')
    args = parser.parse_args()

    built = json.loads((ROOT / DESCRIPTOR).read_text(encoding='utf-8'))
    committed = json.loads(git_text('show', f'HEAD:{DESCRIPTOR}'))
    committed_sha = hashlib.sha256(git('show', f'HEAD:{ARCHIVE}')).hexdigest()

    needed, reason = needs_commit(built, committed, committed_sha, args.refresh == 'true')
    print(reason, file=sys.stderr)
    print('true' if needed else 'false')
    return 0 if needed else 1


if __name__ == '__main__':
    sys.exit(main())
