"""Keep the active server installation and the one available for rollback."""
import json
from pathlib import Path
import re
import shutil

MANAGED_RELEASE = re.compile(r'(?:vanilla|plus|modded)-[0-9a-f]{16}')
STATE_KEYS = ('active', 'previous', 'update_trial', 'mods_trial')


def _references(state):
    if not isinstance(state, dict):
        raise ValueError('Некорректное состояние установок сервера')
    if state.get('update_trial') is not None and type(state['update_trial']) is not bool:
        raise ValueError('Некорректное состояние пробного обновления')
    if state.get('mods_trial') is not None and (not isinstance(state['mods_trial'], str) or not state['mods_trial']):
        raise ValueError('Некорректное состояние восстановления модов')
    return {key: state.get(key) for key in STATE_KEYS}


def _mounts():
    path = Path('/proc/self/mountinfo')
    if not path.exists():
        return []
    # mountinfo escapes whitespace/backslashes in paths using octal sequences.
    return [Path(re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), line.split()[4]))
            for line in path.read_text().splitlines()]


def prune_releases(base, expected_state):
    """Caller must hold the manager's mutation lock, with no install in flight.

    Missing or inconsistent state keeps every release. Only generated immediate
    children are managed; world/config/backup directories are outside this root.
    """
    base = Path(base)
    root = base / 'releases'
    state_path = base / 'state.json'
    if root.is_symlink() or not root.is_dir() or not state_path.is_file() or state_path.is_symlink():
        return []
    if root.resolve() != base.resolve() / 'releases':
        return []
    state = _references(json.loads(state_path.read_text(encoding='utf-8')))
    if state != _references(expected_state) or not state['active'] or state['update_trial'] or state['mods_trial']:
        return []
    keep = set()
    for name in (state['active'], state['previous']):
        if name is None:
            continue
        if not isinstance(name, str) or name in {'.', '..'} or not re.fullmatch(r'[a-zA-Z0-9._-]+', name):
            return []
        folder = root / name
        metadata = folder / 'hearth.json'
        if folder.is_symlink() or not folder.is_dir() or metadata.is_symlink() or not metadata.is_file():
            return []
        info = json.loads(metadata.read_text(encoding='utf-8'))
        if not isinstance(info, dict) or not isinstance(info.get('game'), str) or not re.fullmatch(r'\d+\.\d+\.\d+', info['game']):
            return []
        keep.add(name)
    root_identity = root.stat()
    mounts = _mounts()
    deleted = []
    for folder in sorted(root.iterdir()):
        if folder.name in keep or not MANAGED_RELEASE.fullmatch(folder.name) or folder.is_symlink() or not folder.is_dir():
            continue
        if any(folder.resolve() == mount or folder.resolve() in mount.parents for mount in mounts):
            continue
        # A changed state/root means an external operation took over: stop.
        if _references(json.loads(state_path.read_text(encoding='utf-8'))) != state:
            break
        current_root = root.stat()
        if root.is_symlink() or (current_root.st_dev, current_root.st_ino) != (root_identity.st_dev, root_identity.st_ino):
            break
        if folder.is_symlink() or folder.resolve().parent != root.resolve():
            break
        shutil.rmtree(folder)  # Does not follow the normal BepInEx/config link.
        deleted.append(folder.name)
    return deleted
