"""Portable worlds: a narrow ZIP format, independent of a server's credentials."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import tempfile
import time
import zipfile
from configuration import Configuration, atomic_text, world_name, default_world, cfg_entries

MAX_UPLOAD = 1024 ** 3
MAX_EXPANDED = 2 * MAX_UPLOAD
MAX_FILES = 10000
MAX_MANIFEST = 2 * 1024 * 1024
MOD_NAMES = ('org.bepinex.plugins.valheim_plus.cfg', 'valheim_plus.cfg')


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def chunk_file(name):
    return len(name) <= 128 and bool(re.fullmatch(r'_main\.[0-9]+\.(?:db2|fwl2|chunks|ok)|[A-Za-z0-9_-]+\.chunk', name))


def validate_chunk_set(names):
    names = set(names)
    if not names or len(names) > MAX_FILES or not all(chunk_file(n) for n in names):
        raise ValueError('Недопустимый состав папки мира')
    generations = {n[:-3] for n in names if n.endswith('.ok')}
    if not any(all(g + suffix in names for suffix in ('.db2', '.fwl2', '.chunks', '.ok')) for g in generations):
        raise ValueError('В папке мира нет завершённого сохранения (.db2, .fwl2, .chunks, .ok)')


def read_package(path, target):
    """Never extract archive paths: only copy explicitly allowed regular files."""
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            names = [m.filename for m in members]
            allowed = {'manifest.json', 'world.db', 'world.fwl', 'valheim_plus.cfg'}
            chunk_names = [n[6:] for n in names if n.startswith('world/') and chunk_file(n[6:])]
            allowed.update('world/'+n for n in chunk_names)
            if len(names) > MAX_FILES + 2 or len(names) != len(set(names)) or not set(names) <= allowed or 'manifest.json' not in names:
                raise ValueError('Архив не является экспортом мира Hearth: неверный состав файлов')
            if sum(m.file_size for m in members) > MAX_EXPANDED:
                raise ValueError('Распакованный мир превышает 2 ГиБ')
            for member in members:
                kind = stat.S_IFMT(member.external_attr >> 16)
                limit = MAX_MANIFEST if member.filename == 'manifest.json' else 2*1024*1024 if member.filename.endswith('.cfg') else MAX_EXPANDED
                if kind not in (0, stat.S_IFREG) or member.flag_bits & 1 or not 0 < member.file_size <= limit:
                    raise ValueError('Недопустимый тип или размер файла в архиве')
                if member.filename.startswith('world/'):
                    (target/'world').mkdir(exist_ok=True)
                with archive.open(member) as source, (target/member.filename).open('wb') as out:
                    remaining = member.file_size
                    while remaining:
                        chunk = source.read(min(1024*1024, remaining))
                        if not chunk:
                            raise ValueError('Архив обрезан')
                        out.write(chunk)
                        remaining -= len(chunk)
                    if source.read(1):
                        raise ValueError('Неверный размер файла')
            meta = json.loads((target/'manifest.json').read_text(encoding='utf-8'))
            if not isinstance(meta, dict) or meta.get('format') != 'hearth-world' or meta.get('version') not in (1, 2):
                raise ValueError('Неизвестный формат экспорта')
            if meta['version'] == 1:
                if chunk_names or not {'world.db', 'world.fwl'} <= set(names):
                    raise ValueError('Архив не является экспортом мира Hearth: неверный состав файлов')
            else:
                if meta.get('layout') != 'directory' or {'world.db','world.fwl'} & set(names):
                    raise ValueError('Архив не является экспортом мира Hearth: неверный состав файлов')
                validate_chunk_set(chunk_names)
            world_name(meta.get('world'))
            if meta.get('mode') not in ('plus','vanilla','modded') or not isinstance(meta.get('game'),str) or not re.fullmatch(r'\d+\.\d+\.\d+',meta['game']):
                raise ValueError('Не указаны режим и версия игры')
            if (meta['mode']=='plus') != ('valheim_plus.cfg' in names):
                raise ValueError('Для мира V+ обязателен конфиг мода')
            if meta['mode']=='plus':
                if not isinstance(meta.get('mod'),str) or not re.fullmatch(r'\d+(?:\.\d+){2,3}',meta['mod']):
                    raise ValueError('Не указана версия V+')
                cfg = (target/'valheim_plus.cfg').read_text(encoding='utf-8-sig')
                if '\0' in cfg or not cfg_entries(cfg):
                    raise ValueError('Конфиг V+ пуст или повреждён')
            hashes = meta.get('sha256')
            if not isinstance(hashes,dict) or set(hashes) != set(names)-{'manifest.json'} or any(digest(target/n) != h for n,h in hashes.items()):
                raise ValueError('Контрольная сумма файлов мира не совпадает')
            return meta
    except (zipfile.BadZipFile, UnicodeError, KeyError, TypeError, NotImplementedError) as e:
        raise ValueError('Повреждённый или неподдерживаемый архив мира') from e


def compatible(manager, meta):
    installed = manager.metadata()
    if not installed:
        raise ValueError('Сначала установите сервер во вкладке «Обновления»')
    if installed.get('mode','plus') != meta['mode']:
        raise ValueError('Режимы не совпадают. Сначала установите '+{'plus':'Valheim Plus','modded':'BepInEx','vanilla':'ванильный сервер'}[meta['mode']])
    if installed.get('game') != meta['game'] or meta['mode']=='plus' and installed.get('mod') != meta['mod']:
        raise ValueError('Для переноса нужны одинаковые версии игры и V+ на обоих серверах. Обновите их перед экспортом')


def prepare_settings(manager, meta, directory):
    (directory/'config').mkdir()
    config = Configuration(directory)
    atomic_text(config.path, json.dumps(manager.config.load()))
    _, content = config.prepare({'scope':'world','revision':config.revision(), 'values':{'name':meta['world'],'rules':meta.get('rules')}})
    return content


def export_world(manager):
    versions = manager.metadata()
    if not versions:
        raise ValueError('Сервер ещё не установлен')
    was_running = manager.running()
    manager.stop()
    try:
        settings = manager.config.load()
        name = world_name(settings['world_name'])
        folder = manager.base/'saves/worlds_local'
        directory = folder/name
        if folder.is_symlink() or directory.is_symlink():
            raise ValueError('Ссылки в пути мира не поддерживаются')
        chunked = directory.exists()
        if chunked:
            if not directory.is_dir():
                raise ValueError('Недопустимый состав папки мира')
            entries = list(directory.iterdir())
            validate_chunk_set(p.name for p in entries)
            files = {'world/'+p.name:p for p in entries}
        else:
            files = {f'world{suffix}':folder/(name+suffix) for suffix in ('.db','.fwl')}

        mode = versions.get('mode','plus')
        if mode == 'plus':
            cfg = manager.config.mod_path()
            if not cfg:
                raise ValueError('Конфиг V+ ещё не создан. Сначала запустите сервер с модом')
            if cfg.stat().st_size > 2*1024*1024 or not cfg_entries(cfg.read_text(encoding='utf-8-sig')):
                raise ValueError('Конфиг V+ пуст, повреждён или превышает 2 МиБ')
            files['valheim_plus.cfg'] = cfg
        if any(not p.is_file() or p.is_symlink() or p.stat().st_size == 0 for p in files.values()):
            raise ValueError('Файлы выбранного мира отсутствуют, пусты или являются ссылками')
        size = sum(p.stat().st_size for p in files.values())
        if size > MAX_EXPANDED or shutil.disk_usage(manager.base).free < size + 64*1024*1024:
            raise ValueError('Мир превышает 2 ГиБ или недостаточно места для экспорта')
        exports = manager.base/'exports'; exports.mkdir(exist_ok=True)
        filename = 'world-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4)+'.zip'
        temporary = exports/(filename+'.tmp')
        try:
            meta = {'format':'hearth-world','version':2 if chunked else 1,'world':name,'mode':mode,'game':versions['game'], 'mod':versions.get('mod'), 'created':time.time(), 'rules':settings['worlds'].get(name,default_world()), 'sha256':{n:digest(p) for n,p in files.items()}}
            if chunked:meta['layout']='directory'
            if len(json.dumps(meta,ensure_ascii=False).encode('utf-8')) > MAX_MANIFEST:
                raise ValueError('Слишком много файлов для экспорта мира')
            with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
                archive.writestr('manifest.json',json.dumps(meta,ensure_ascii=False))
                for n,p in files.items():archive.write(p,n)
            if temporary.stat().st_size > MAX_UPLOAD:
                raise ValueError('Архив превышает лимит переноса 1 ГиБ')
            temporary.replace(exports/filename)
        finally:
            temporary.unlink(missing_ok=True)
        manager.store.event('export','Экспортирован мир '+name)
    finally:
        if was_running:manager.start()


def stage_import(manager, stream, size):
    if not 0 < size <= MAX_UPLOAD:
        raise ValueError('Размер архива должен быть от 1 байта до 1 ГиБ')
    if shutil.disk_usage(manager.base).free < size + MAX_EXPANDED + 64*1024*1024:
        raise ValueError('Недостаточно места для загрузки и проверки архива (нужно до 3 ГиБ)')
    incoming = manager.base/'incoming';incoming.mkdir(exist_ok=True)
    path = incoming/(secrets.token_hex(16)+'.zip')
    try:
        with path.open('wb') as out:
            remaining=size
            while remaining:
                chunk=stream.read(min(1024*1024,remaining))
                if not chunk:raise ValueError('Загрузка архива прервана')
                out.write(chunk);remaining-=len(chunk)
        with tempfile.TemporaryDirectory(dir=manager.base) as tmp:
            target=Path(tmp)
            meta=read_package(path,target)
            compatible(manager,meta)
            prepare_settings(manager,meta,target)
        token=path.stem
        previous=manager.pending_import
        manager.pending_import={'token':token,'meta':meta,'expires':time.time()+3600}
        if previous:(incoming/(previous['token']+'.zip')).unlink(missing_ok=True)
        return {'token':token,'world':meta['world'],'mode':meta['mode'],'game':meta['game'],'mod':meta.get('mod'), 'expires':manager.pending_import['expires']}
    except Exception:
        path.unlink(missing_ok=True)
        raise


def import_world(manager, token):
    pending=manager.pending_import
    if not isinstance(token,str) or not pending or token != pending['token'] or pending['expires'] < time.time():
        raise ValueError('Загрузите и проверьте архив заново')
    path=manager.base/'incoming'/(token+'.zip')
    with tempfile.TemporaryDirectory(dir=manager.base) as tmp:
        target=Path(tmp)
        meta=read_package(path,target)
        compatible(manager,meta)  # Recheck after possible server updates since upload.
        content=prepare_settings(manager,meta,target)
        manager.stop()
        manager.backup('pre-import')
        folder=manager.base/'saves/worlds_local';folder.mkdir(exist_ok=True)
        if folder.is_symlink():
            raise ValueError('Ссылки в пути мира не поддерживаются')
        directory=folder/meta['world']
        replacements={directory:target/'world' if meta['version']==2 else None}
        for suffix in ('.db','.fwl','.db.old','.fwl.old'):
            destination=folder/(meta['world']+suffix)
            replacements[destination]=target/('world'+suffix) if meta['version']==1 and suffix in ('.db','.fwl') else None
        replacements[manager.config.path]=None
        if meta['mode']=='plus':
            # Keep the target's canonical filename; remove an alternate duplicate.
            cfg=manager.config.mod_path() or manager.base/'config'/MOD_NAMES[0]
            replacements[cfg]=target/'valheim_plus.cfg'
            for name in MOD_NAMES:
                other=manager.base/'config'/name
                if other != cfg and other.exists():replacements[other]=None
        # Move the entire old directory aside; never merge generations or chunks.
        # The full pre-import backup remains available if rollback itself fails.
        for destination in replacements:
            if destination.is_symlink():
                raise ValueError('Ссылки в пути мира не поддерживаются')
        originals={}
        try:
            for i,(destination,source) in enumerate(replacements.items()):
                if destination.exists():
                    saved=target/('original-'+str(i))
                    os.replace(destination,saved)
                    originals[destination]=saved
                else:originals[destination]=None
                if destination==manager.config.path:atomic_text(destination,content)
                elif source:os.replace(source,destination)
        except Exception:
            for destination,saved in reversed(list(originals.items())):
                if destination.is_dir():shutil.rmtree(destination)
                else:destination.unlink(missing_ok=True)
                if saved:os.replace(saved,destination)
            raise
    path.unlink(missing_ok=True)
    manager.pending_import=None
    manager.store.event('import','Импортирован мир '+meta['world']+'. Сервер остановлен: проверьте настройки и запустите его.')
