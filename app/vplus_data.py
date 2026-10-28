"""Keep V+'s server map state outside disposable game installations."""
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import tempfile


def _regular_folder(path):
    if path.is_symlink() or not path.is_dir():
        raise ValueError('Каталог данных V+ должен быть обычной папкой внутри данных сервера')


def _same(left, right):
    if right.is_symlink() or not right.is_file():
        return False
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open('rb') as a, right.open('rb') as b:
        return hashlib.file_digest(a, 'sha256').digest() == hashlib.file_digest(b, 'sha256').digest()


def prepare_vplus_data(base, release, *, migrate=True):
    """Called only while the game is stopped and the manager lock is held.

    A staged version probe must use migrate=False: its disposable world's map
    files are not server data. Old source files remain in the release, renamed,
    after a successful migration; failures never delete the source directory.
    """
    base = Path(base).resolve()
    release = Path(release).absolute()
    root = base / 'releases'
    saves = base / 'saves'
    _regular_folder(root)
    _regular_folder(saves)
    if release.is_symlink() or release.parent.resolve() != root.resolve() or not release.is_dir():
        raise ValueError('Каталог установки V+ должен находиться внутри releases')
    bepinex = release / 'BepInEx'
    if bepinex.is_symlink() or bepinex.exists() and not bepinex.is_dir():
        raise ValueError('Каталог BepInEx не должен быть ссылкой')
    bepinex.mkdir(exist_ok=True)
    target = saves / 'vplus-data'
    if target.is_symlink() or target.exists() and not target.is_dir():
        raise ValueError('Постоянный каталог данных V+ не должен быть ссылкой или файлом')
    target.mkdir(mode=0o700, exist_ok=True)
    if any(p.is_symlink() or not p.is_file() for p in target.iterdir()):
        raise ValueError('В постоянных данных V+ есть ссылки или подпапки; проверьте каталог')
    source = bepinex / 'vplus-data'
    if source.is_symlink():
        if source.resolve() != target:
            raise ValueError('Ссылка данных V+ указывает за пределы постоянного каталога')
        return
    if source.exists():
        _regular_folder(source)
        files = list(source.iterdir())
        if any(p.is_symlink() or not p.is_file() for p in files):
            raise ValueError('В старых данных V+ есть ссылки или подпапки; перенесите данные вручную')
        if migrate:
            for path in files:
                destination = target / path.name
                if (destination.exists() or destination.is_symlink()) and not _same(path, destination):
                    raise ValueError('Конфликт данных V+: ' + path.name + '. Старые файлы сохранены; сравните их перед переносом')
            for path in files:
                destination = target / path.name
                if destination.exists():
                    continue
                descriptor, name = tempfile.mkstemp(prefix='.hearth-', suffix='.tmp', dir=target)
                temporary = Path(name)
                try:
                    with os.fdopen(descriptor, 'wb') as out, path.open('rb') as src:
                        shutil.copyfileobj(src, out)
                        out.flush()
                        os.fsync(out.fileno())
                    # Publishing by link is atomic and never overwrites a file.
                    os.link(temporary, destination, follow_symlinks=False)
                finally:
                    temporary.unlink(missing_ok=True)
        previous = bepinex / ('vplus-data.hearth-migrated-' + secrets.token_hex(8))
        source.rename(previous)
        try:
            source.symlink_to(target, target_is_directory=True)
        except Exception:
            previous.rename(source)
            raise
    else:
        source.symlink_to(target, target_is_directory=True)
