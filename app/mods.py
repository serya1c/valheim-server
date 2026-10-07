"""Transactional, private storage for additional BepInEx plugins.

Mods are executable game code. ZIP validation confines installation paths; it
does not make a third party DLL trustworthy. This module never executes a mod.
"""
import copy
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import threading
import unicodedata
from urllib.parse import unquote, urlsplit
import urllib.error
import urllib.request
import uuid
import zipfile


MAX_ARCHIVE = 128 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_FILE = 64 * 1024 * 1024
MAX_FILES = 4096
MAX_PACKAGES = 64
MAX_TRANSACTION = 512 * 1024 * 1024
MAX_CLIENT_FILES = 5000
MAX_JSON = 2 * 1024 * 1024
SCOPES = {'server', 'client', 'both'}
IDENT = re.compile(r'([A-Za-z0-9_]{1,100})-([A-Za-z0-9_]{1,100})(?:-(\d+\.\d+\.\d+(?:\.\d+)?))?\Z')
VERSION = re.compile(r'\d+\.\d+\.\d+(?:\.\d+)?\Z')
LOADER_ID = 'denikson-BepInExPack_Valheim'
API = 'https://thunderstore.io/api/experimental/package/'
NETWORK_HOSTS = {'thunderstore.io', 'www.thunderstore.io', 'gcdn.thunderstore.io', 'ccdn.thunderstore.io'}
FORBIDDEN_SUFFIXES = {'.exe', '.bat', '.cmd', '.ps1', '.sh', '.so', '.dylib', '.msi', '.com', '.scr', '.vbs', '.py', '.js', '.jar', '.lnk', '.cfg', '.ini', '.toml', '.reg'}
PRIVATE_DIRS = {'config', 'configs', 'patchers', 'core', 'cache', 'logs', 'profiles', 'monomod'}
DOC_NAMES = {'readme.md', 'readme.txt', 'changelog.md', 'changelog.txt', 'manifest.json', 'icon.png', 'license', 'license.txt', 'license.md'}
RESERVED = re.compile(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?\Z', re.I)


def _sync_directory(path):
    # Directory fsync makes the manifest rename durable on Linux. Windows
    # does not expose the same operation through os.open.
    with contextlib.suppress(OSError):
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _network_url(url):
    if not isinstance(url, str) or not 1 <= len(url) <= 2000:
        raise ValueError('Недопустимый адрес скачивания Thunderstore')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in NETWORK_HOSTS or parsed.username
            or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError('Скачивание модов разрешено только с HTTPS Thunderstore')
    return url


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, _network_url(newurl))


def _fetch(url, limit=MAX_ARCHIVE):
    request = urllib.request.Request(_network_url(url), headers={'User-Agent': 'Hearth-ModManager/1.0', 'Accept': 'application/json, application/zip, */*'})
    try:
        with urllib.request.build_opener(_Redirects()).open(request, timeout=40) as response:
            _network_url(response.url)
            length = response.headers.get('Content-Length')
            if length and int(length) > limit:
                raise ValueError('Файл мода превышает допустимый размер')
            chunks, size = [], 0
            while True:
                chunk = response.read(min(1024 * 1024, limit + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise ValueError('Файл мода превышает допустимый размер')
                chunks.append(chunk)
            return b''.join(chunks)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ValueError('Не удалось скачать пакет Thunderstore') from error


def _json(url):
    try:
        result = json.loads(_fetch(url, MAX_JSON))
    except (ValueError, UnicodeError) as error:
        raise ValueError('Thunderstore вернул недопустимые данные пакета') from error
    if not isinstance(result, dict):
        raise ValueError('Thunderstore вернул недопустимые данные пакета')
    return result


def _reference(source, exact=False):
    if not isinstance(source, str) or not 1 <= len(source) <= 600 or any(ord(c) < 32 for c in source):
        raise ValueError('Укажите URL Thunderstore или Author-Package-version')
    value = source.strip()
    if '://' in value:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.hostname not in {'thunderstore.io', 'www.thunderstore.io', 'valheim.thunderstore.io'}
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or parsed.query or parsed.fragment):
            raise ValueError('Укажите HTTPS URL пакета Thunderstore')
        parts = [unquote(part) for part in parsed.path.strip('/').split('/')]
        if parts[:1] == ['package']:
            parts = parts[1:]
        elif parts[:3] == ['c', 'valheim', 'p']:
            parts = parts[3:]
        else:
            raise ValueError('Укажите страницу пакета Valheim на Thunderstore')
        if len(parts) not in (2, 3):
            raise ValueError('Укажите страницу пакета Valheim на Thunderstore')
        value = '-'.join(parts)
    match = IDENT.fullmatch(value)
    if not match or exact and not match[3]:
        raise ValueError('Пакет: Author-Package; зависимость: Author-Package-1.2.3')
    return match[1] + '-' + match[2], match[3]


def _scope(value):
    if value not in SCOPES:
        raise ValueError('Область мода: server, client или both')
    return value


def _covers(scope, required):
    return scope == 'both' or scope == required


def _join_scope(first, second):
    return first if first == second else 'both'


def _path(value):
    if not isinstance(value, str) or not value or len(value.encode('utf-16-le')) // 2 > 240 or '\\' in value:
        raise ValueError('Недопустимый путь внутри ZIP мода')
    value = value.rstrip('/')
    parts = value.split('/')
    if any(not part or part in ('.', '..') or len(part) > 100 or part[-1:] in (' ', '.')
           or any(c in part for c in ':<>"|?*') or RESERVED.fullmatch(part) or unicodedata.normalize('NFC', part) != part
           or any(ord(c) < 32 or ord(c) == 127 for c in part) for part in parts):
        raise ValueError('Недопустимый путь внутри ZIP мода')
    return '/'.join(parts)


def _entries(archive):
    entries, known, spellings, total = [], {}, {}, 0
    if len(archive.infolist()) > MAX_FILES:
        raise ValueError('В ZIP мода слишком много файлов')
    for item in archive.infolist():
        # Thunderstore packages commonly use Windows ZIP separators. Normalize
        # them before traversal/collision checks on every OS; inspect the
        # original name because ZipInfo truncates NULs on construction.
        name = _path(item.orig_filename.replace('\\', '/'))
        directory = item.orig_filename.endswith(('/', '\\'))
        key = name.casefold()
        parts = name.split('/')
        for index in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:index])
            if prefix.casefold() in spellings and spellings[prefix.casefold()] != prefix:
                raise ValueError('ZIP мода содержит коллизию регистра каталогов')
            spellings[prefix.casefold()] = prefix
        mode = item.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if (item.flag_bits & 1 or kind not in (0, stat.S_IFREG, stat.S_IFDIR)
                or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
            raise ValueError('ZIP мода содержит ссылку, специальный или зашифрованный файл')
        if key in known:
            raise ValueError('ZIP мода содержит повторяющиеся пути или коллизию регистра')
        for parent in PurePosixPath(key).parents:
            if str(parent) != '.' and known.get(str(parent)) is False:
                raise ValueError('ZIP мода содержит коллизию файла и каталога')
        if not directory and any(other.startswith(key + '/') for other in known):
            raise ValueError('ZIP мода содержит коллизию файла и каталога')
        known[key] = directory
        if item.file_size < 0 or item.file_size > MAX_FILE or item.file_size > max(1024 * 1024, item.compress_size * 200):
            raise ValueError('Файл внутри ZIP мода превышает допустимый размер')
        total += item.file_size
        if total > MAX_EXPANDED:
            raise ValueError('Распакованный мод превышает допустимый размер')
        entries.append((item, name))
    return entries


def _plugin_path(name):
    parts = name.split('/')
    lower = [part.casefold() for part in parts]
    package_metadata = len(parts) == 1 and lower[0] in DOC_NAMES
    if (any(part in ('patchers', 'monomod') for part in lower[:-1])
            or PurePosixPath(parts[-1]).suffix.casefold() in ('.so', '.dylib')):
        raise ValueError('Мод требует patcher или native runtime; поддерживаются только плагины BepInEx')
    if any(part in PRIVATE_DIRS for part in lower[:-1]):
        return None
    if 'bepinex' in lower:
        at = lower.index('bepinex')
        if lower[at + 1:at + 2] != ['plugins']:
            return None
        parts = parts[at + 2:]
    elif lower[:1] == ['plugins']:
        parts = parts[1:]
    if not parts or package_metadata or PurePosixPath(parts[-1]).suffix.casefold() in FORBIDDEN_SUFFIXES:
        return None
    filename = parts[-1].casefold()
    if (filename == 'valheimplus.dll' or filename.startswith(('bepinex.', 'mono.cecil', 'monomod.'))
            or filename in ('bepinex.dll', '0harmony.dll', '0harmony20.dll', 'harmonyxinterop.dll', 'winhttp.dll')):
        raise ValueError('Загрузчик и Valheim Plus управляются панелью отдельно')
    return '/'.join(parts)


def _external(ident):
    namespace, name = ident.split('-', 1)
    if name.casefold() == 'bepinexpack_valheim':
        if ident != LOADER_ID:
            raise ValueError('Поддерживается только официальный denikson-BepInExPack_Valheim')
        return 'loader'
    if 'valheimplus' in name.casefold().replace('_', ''):
        return 'plus'
    return None


def _public(package):
    return {key: copy.deepcopy(package[key]) for key in
            ('id', 'name', 'version', 'enabled', 'scope', 'source', 'source_url', 'dependencies', 'description', 'size')}


class ModManager:
    def __init__(self, base, external_versions=None):
        self.root = Path(base).resolve() / 'mods'
        self.lock = threading.RLock()
        self.external_versions = external_versions or {}
        self._directory(self.root)
        self._directory(self.root / 'packages')
        self.manifest = self.root / 'manifest.json'
        self._load()
        self._collect()

    def _directory(self, path):
        if path != self.root and self.root not in path.parents:
            raise ValueError('Каталог мода находится вне приватного хранилища')
        current = self.root
        for part in ((), path.relative_to(self.root).parts):
            for name in part:
                current = current / name
            if current.is_symlink() or current.exists() and not current.is_dir():
                raise ValueError('Каталог мода не должен быть ссылкой или файлом')
        # Inspect every existing ancestor, not only the final directory.
        for current in (self.root, *path.parents):
            if current == self.root.parent:
                break
            if current.is_symlink():
                raise ValueError('Каталог мода не должен быть ссылкой')
        path.mkdir(parents=True, exist_ok=True)

    def _load(self):
        if not self.manifest.exists():
            self.state = {'schema': 1, 'revision': 'empty', 'packages': [], 'loader': None}
            return
        if self.manifest.is_symlink() or self.manifest.stat().st_size > MAX_JSON:
            raise ValueError('Недопустимый манифест хранилища модов')
        try:
            state = json.loads(self.manifest.read_text(encoding='utf-8'))
            if (state.get('schema') != 1 or not isinstance(state.get('revision'), str)
                    or not isinstance(state.get('packages'), list) or len(state['packages']) > MAX_PACKAGES):
                raise ValueError()
            ids = set()
            for package in state['packages']:
                ident, version = _reference(package['id'])
                if version or ident.casefold() in ids or not VERSION.fullmatch(package['version']):
                    raise ValueError()
                ids.add(ident.casefold())
                _scope(package['scope'])
                if type(package['enabled']) is not bool or package['source'] not in ('thunderstore', 'manual'):
                    raise ValueError()
                list(self._stored_files(package, read=False))
            if state.get('loader'):
                list(self._stored_files(state['loader'], read=False))
            self.state = state
        except (ValueError, KeyError, TypeError, AttributeError, OSError) as error:
            raise ValueError('Не удалось прочитать манифест хранилища модов') from error

    def _publish(self, state):
        state = copy.deepcopy(state)
        state['revision'] = uuid.uuid4().hex
        encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8')
        if len(encoded) > MAX_JSON:
            raise ValueError('Манифест модов превышает допустимый размер')
        fd, name = tempfile.mkstemp(prefix='.manifest-', dir=self.root)
        temporary = Path(name)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.manifest)
            self.state = state
            _sync_directory(self.root)
            self._collect()
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)

    def _collect(self):
        """Unreferenced immutable trees are safe to remove after publication."""
        live = {package['storage'] for package in self.state['packages']}
        if self.state.get('loader'):
            live.add(self.state['loader']['storage'])
        try:
            for folder in (self.root / 'packages').iterdir():
                if re.fullmatch('[a-f0-9]{32}', folder.name) and folder.name not in live and folder.is_dir() and not folder.is_symlink():
                    shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            # Publication has already succeeded. Never roll it back because
            # optional garbage collection was denied by the filesystem.
            pass

    def _versions(self):
        value = self.external_versions() if callable(self.external_versions) else self.external_versions
        return value if isinstance(value, dict) else {}

    def _check_external(self, ident, version, external_versions=None):
        external = _external(ident)
        if external == 'loader':
            if not version.startswith('5.4.'):
                raise ValueError('Поддерживаются зависимости BepInEx только версии 5.4')
        elif external == 'plus':
            installed = (self._versions() if external_versions is None else external_versions).get('ValheimPlus')
            if installed != version:
                raise ValueError(f'Зависимость {ident}-{version}: установленная версия Valheim Plus {installed or "отсутствует"} не совпадает')
        return external

    def view(self):
        with self.lock:
            return {'packages': [_public(package) | {'files': len(package['files'])} for package in self.state['packages']],
                    'revision': self.state['revision'], 'loader': self.loader_info(),
                    'limits': {'archive_bytes': MAX_ARCHIVE, 'expanded_bytes': MAX_EXPANDED, 'packages': MAX_PACKAGES}}

    def loader_info(self):
        with self.lock:
            loader = self.state.get('loader')
            return {'version': loader['version'] if loader else None, 'ready': bool(loader)}

    def _metadata(self, ident, version=None):
        namespace, name = ident.split('-', 1)
        result = _json(API + namespace + '/' + name + '/' + (version + '/' if version else ''))
        if version is None:
            listings = result.get('community_listings', [])
            if listings and not any(item.get('community') == 'valheim' for item in listings):
                raise ValueError('Пакет Thunderstore не относится к Valheim')
            result = result.get('latest', {})
        if not isinstance(result, dict):
            raise ValueError('Thunderstore вернул недопустимые данные пакета')
        number = result.get('version_number')
        if (not isinstance(number, str) or not VERSION.fullmatch(number) or version and version != number
                or result.get('namespace', namespace) != namespace or result.get('name', name) != name
                or result.get('is_active') is False):
            raise ValueError('Thunderstore вернул другую или недоступную версию пакета')
        dependencies = result.get('dependencies', [])
        if not isinstance(dependencies, list) or len(dependencies) > MAX_PACKAGES:
            raise ValueError('Недопустимый список зависимостей мода')
        for dependency in dependencies:
            _reference(dependency, exact=True)
        result['dependencies'] = list(dict.fromkeys(dependencies))
        result['download_url'] = _network_url(result.get('download_url', ''))
        return result

    def _stored_files(self, package, read=True):
        storage = package['storage']
        if not isinstance(storage, str) or not re.fullmatch(r'[a-f0-9]{32}', storage):
            raise ValueError('Недопустимый каталог пакета')
        folder = self.root / 'packages' / storage
        if folder.is_symlink():
            raise ValueError('Каталог пакета не должен быть ссылкой')
        files, seen = package['files'], set()
        if not isinstance(files, list) or len(files) > MAX_FILES:
            raise ValueError('Недопустимый список файлов пакета')
        for entry in files:
            path = _path(entry['path'])
            key = path.casefold()
            if key in seen or not isinstance(entry['size'], int) or not 0 <= entry['size'] <= MAX_FILE or not re.fullmatch('[a-f0-9]{64}', entry['sha256']):
                raise ValueError('Недопустимый список файлов пакета')
            seen.add(key)
            if read:
                file = folder / path
                if any(parent.is_symlink() for parent in (file, *file.parents) if parent != self.root.parent and self.root in parent.parents or parent == self.root):
                    raise ValueError('Файл пакета не должен быть ссылкой')
                if not file.is_file() or file.stat().st_size != entry['size']:
                    raise ValueError('Файлы сохранённого мода повреждены')
                data = file.read_bytes()
                if hashlib.sha256(data).hexdigest() != entry['sha256']:
                    raise ValueError('Контрольная сумма сохранённого мода не совпадает')
                yield path, data
        if not read:
            # This method is a generator; exhaust it at validation call sites.
            return

    def _store(self, payload, selector, loader=False):
        if len(payload) > MAX_ARCHIVE:
            raise ValueError('Файл мода превышает допустимый размер')
        storage = uuid.uuid4().hex
        folder = self.root / 'packages' / storage
        self._directory(folder)
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                entries = _entries(archive)
                manifests = [item for item, name in entries if name.casefold() == 'manifest.json' and not item.is_dir()]
                metadata = {}
                if manifests:
                    if manifests[0].file_size > 65536:
                        raise ValueError('Манифест ZIP слишком большой')
                    metadata = json.loads(archive.read(manifests[0]))
                    if not isinstance(metadata, dict):
                        raise ValueError('Недопустимый манифест ZIP')
                files, seen, spellings = [], {}, {}
                for item, name in entries:
                    if item.orig_filename.endswith(('/', '\\')):
                        continue
                    path = selector(name)
                    if path is None:
                        continue
                    path = _path(path)
                    key = path.casefold()
                    parts = path.split('/')
                    for index in range(1, len(parts) + 1):
                        prefix = '/'.join(parts[:index])
                        if prefix.casefold() in spellings and spellings[prefix.casefold()] != prefix:
                            raise ValueError('Коллизия регистра путей плагинов после распаковки')
                        spellings[prefix.casefold()] = prefix
                    if key in seen or any(key.startswith(other + '/') or other.startswith(key + '/') for other in seen):
                        raise ValueError('Коллизия путей плагинов после распаковки')
                    seen[key] = True
                    data = archive.read(item)
                    if len(data) != item.file_size:
                        raise ValueError('Повреждённый ZIP мода')
                    target = folder / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open('wb') as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    files.append({'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
                if not files or not loader and not any(entry['path'].casefold().endswith('.dll') for entry in files):
                    raise ValueError('ZIP не содержит поддерживаемых DLL плагинов BepInEx')
                for directory in sorted([path for path in folder.rglob('*') if path.is_dir()], key=lambda path: len(path.parts), reverse=True):
                    _sync_directory(directory)
                _sync_directory(folder)
                _sync_directory(folder.parent)
                return {'storage': storage, 'files': sorted(files, key=lambda entry: entry['path'].casefold()),
                        'size': sum(entry['size'] for entry in files)}, metadata
        except (zipfile.BadZipFile, RuntimeError, UnicodeError, json.JSONDecodeError) as error:
            shutil.rmtree(folder)
            raise ValueError('Не удалось прочитать ZIP мода') from error
        except Exception:
            shutil.rmtree(folder)
            raise

    def _validate_graph(self, packages, external_versions=None):
        by_id = {package['id'].casefold(): package for package in packages}
        if len(packages) > MAX_PACKAGES or len(by_id) != len(packages):
            raise ValueError('Слишком много модов или повторяющиеся имена пакетов')
        total, assemblies = 0, {}
        for package in packages:
            total += package['size']
            for entry in package['files']:
                if len(('BepInEx/plugins/HearthMods/' + package['id'] + '/' + entry['path']).encode('utf-16-le')) // 2 > 240:
                    raise ValueError('Путь установленного плагина слишком длинный для Windows')
            if not package['enabled']:
                continue
            for reference in package['dependencies']:
                ident, version = _reference(reference, exact=True)
                if self._check_external(ident, version, external_versions):
                    continue
                dependency = by_id.get(ident.casefold())
                if (not dependency or not dependency['enabled'] or dependency['version'] != version
                        or not _covers(dependency['scope'], package['scope'])):
                    raise ValueError(f'Мод {package["id"]} требует включённую зависимость {reference} в той же области')
            for entry in package['files']:
                if not entry['path'].casefold().endswith('.dll'):
                    continue
                name = PurePosixPath(entry['path']).name.casefold()
                for previous in assemblies.get(name, []):
                    if _join_scope(previous['scope'], package['scope']) != 'both' or 'both' in (previous['scope'], package['scope']):
                        raise ValueError(f'Конфликт DLL {name}: {previous["id"]} и {package["id"]}')
                assemblies.setdefault(name, []).append(package)
        if total > MAX_TRANSACTION:
            raise ValueError('Общий размер модов превышает допустимый размер')

    def _transaction(self, ident, version, scope, payload=None, local_name=None, active=True):
        proposed = copy.deepcopy(self.state)
        packages = {package['id'].casefold(): package for package in proposed['packages']}
        created, visiting, pins = [], set(), {}
        staged_size = 0
        def resolve(current, pin, required, explicit=False, activate=True):
            nonlocal staged_size
            key = current.casefold()
            if pin:
                if key in pins and pins[key] != pin:
                    raise ValueError(f'Конфликт версий зависимости {current}: {pins[key]} и {pin}')
                pins[key] = pin
            if current.casefold() in visiting:
                raise ValueError('Циклическая зависимость модов')
            if self._check_external(current, pin or ''):
                if explicit:
                    raise ValueError('Загрузчик и Valheim Plus управляются панелью отдельно')
                return
            existing = packages.get(current.casefold())
            if existing and not explicit and existing['version'] == pin:
                was_enabled = existing['enabled']
                existing['enabled'] = existing['enabled'] or activate
                existing['scope'] = _join_scope(existing['scope'], required) if was_enabled else required
                visiting.add(current.casefold())
                for dependency in existing['dependencies']:
                    dep_id, dep_version = _reference(dependency, exact=True)
                    resolve(dep_id, dep_version, existing['scope'], activate=existing['enabled'])
                visiting.remove(current.casefold())
                return
            if existing and not explicit and existing['enabled']:
                # Keep an independently enabled dependency available in its
                # old runtime scope while upgrading the shared package.
                activate = True
                required = _join_scope(existing['scope'], required)
            if len(packages) >= MAX_PACKAGES and not existing:
                raise ValueError('Слишком много модов')
            visiting.add(current.casefold())
            if explicit and payload is not None:
                stored, metadata = self._store(payload, _plugin_path)
                created.append(stored['storage'])
                number = metadata.get('version_number', '0.0.0')
                dependencies = metadata.get('dependencies', [])
                if not isinstance(number, str) or not VERSION.fullmatch(number) or not isinstance(dependencies, list) or len(dependencies) > MAX_PACKAGES:
                    raise ValueError('Недопустимая версия или зависимости в манифесте ZIP')
                source, description = 'manual', metadata.get('description', '')
            else:
                metadata = self._metadata(current, pin)
                number, dependencies = metadata['version_number'], metadata['dependencies']
                stored, manifest = self._store(_fetch(metadata['download_url']), _plugin_path)
                created.append(stored['storage'])
                if manifest:
                    manifest_dependencies = manifest.get('dependencies', [])
                    if not isinstance(manifest_dependencies, list):
                        raise ValueError('Недопустимые зависимости в манифесте ZIP')
                    for dependency in manifest_dependencies:
                        _reference(dependency, exact=True)
                    if manifest.get('version_number') != number or set(manifest_dependencies) != set(dependencies):
                        raise ValueError('Манифест ZIP не совпадает с данными Thunderstore')
                source, description = 'thunderstore', metadata.get('description', '')
            staged_size += stored['size']
            if staged_size > MAX_TRANSACTION:
                raise ValueError('Общий размер устанавливаемых модов превышает допустимый размер')
            if key in pins and pins[key] != number:
                raise ValueError(f'Конфликт версий зависимости {current}')
            pins[key] = number
            for dependency in dependencies:
                _reference(dependency, exact=True)
            package = {'id': current, 'name': local_name if explicit and local_name else current.split('-', 1)[1],
                       'version': number, 'enabled': activate, 'scope': required, 'source': source,
                       'source_url': 'https://thunderstore.io/c/valheim/p/' + current.replace('-', '/', 1) + '/' if source == 'thunderstore' else '',
                       'dependencies': list(dict.fromkeys(dependencies)), 'description': str(description)[:2000], **stored}
            packages[current.casefold()] = package
            for dependency in package['dependencies']:
                dep_id, dep_version = _reference(dependency, exact=True)
                resolve(dep_id, dep_version, required, activate=activate)
            visiting.remove(current.casefold())
        try:
            resolve(ident, version, scope, explicit=True, activate=active)
            proposed['packages'] = sorted(packages.values(), key=lambda package: package['id'].casefold())
            self._validate_graph(proposed['packages'])
            self._publish(proposed)
        except Exception:
            for storage in created:
                shutil.rmtree(self.root / 'packages' / storage, ignore_errors=True)
            raise
        return self.view()

    def install(self, source, scope='both'):
        with self.lock:
            ident, version = _reference(source)
            return self._transaction(ident, version, _scope(scope))

    def upload(self, path, name, scope='both'):
        with self.lock:
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name):
                raise ValueError('Укажите название ZIP мода: 1–80 символов')
            slug = re.sub('[^A-Za-z0-9_]+', '_', name.strip()).strip('_')[:70]
            if not slug:
                slug = hashlib.sha256(name.encode()).hexdigest()[:16]
            path = Path(path)
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ARCHIVE:
                raise ValueError('Недопустимый файл ZIP мода или слишком большой размер')
            return self._transaction('local-' + slug, None, _scope(scope), payload=path.read_bytes(), local_name=name.strip())

    def _package(self, ident):
        if not isinstance(ident, str):
            raise ValueError('Укажите идентификатор мода')
        for package in self.state['packages']:
            if package['id'].casefold() == ident.casefold():
                return package
        raise ValueError('Мод не найден')

    def update(self, ident):
        with self.lock:
            package = self._package(ident)
            if package['source'] != 'thunderstore':
                raise ValueError('Локальный ZIP обновляется загрузкой нового архива с тем же названием')
            return self._transaction(package['id'], None, package['scope'], active=package['enabled'])

    def set_enabled(self, ident, enabled):
        with self.lock:
            if type(enabled) is not bool:
                raise ValueError('Состояние мода должно быть логическим значением')
            package = self._package(ident)
            proposed = copy.deepcopy(self.state)
            next(item for item in proposed['packages'] if item['id'] == package['id'])['enabled'] = enabled
            self._validate_graph(proposed['packages'])
            self._publish(proposed)
            return self.view()

    def remove(self, ident):
        with self.lock:
            package = self._package(ident)
            proposed = copy.deepcopy(self.state)
            proposed['packages'] = [item for item in proposed['packages'] if item['id'] != package['id']]
            self._validate_graph(proposed['packages'])
            self._publish(proposed)
            return self.view()

    @staticmethod
    def _release_dir(folder, relative):
        folder = Path(folder).resolve()
        target = folder
        for part in PurePosixPath(relative).parts:
            target = target / part
            if target.is_symlink() or target.exists() and not target.is_dir():
                raise ValueError('Каталог установки мода не должен быть ссылкой или файлом')
            target.mkdir(exist_ok=True)
        return target

    def validate_external(self, external_versions=None):
        with self.lock:
            if external_versions is not None and not isinstance(external_versions, dict):
                raise ValueError('Недопустимый список внешних версий модов')
            self._validate_graph(self.state['packages'], external_versions)
            return True

    def materialize(self, folder, external_versions=None):
        with self.lock:
            self.validate_external(external_versions)
            plugins = self._release_dir(folder, 'BepInEx/plugins')
            target = plugins / 'HearthMods'
            if target.is_symlink() or target.exists() and not target.is_dir():
                raise ValueError('Каталог HearthMods не должен быть ссылкой или файлом')
            stage = plugins / ('.hearth-stage-' + uuid.uuid4().hex)
            previous = plugins / ('.hearth-old-' + uuid.uuid4().hex)
            stage.mkdir()
            published = False
            try:
                for package in self.state['packages']:
                    if package['enabled'] and package['scope'] in ('server', 'both'):
                        for path, data in self._stored_files(package):
                            destination = stage / package['id'] / path
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            destination.write_bytes(data)
                if target.exists():
                    target.replace(previous)
                try:
                    stage.replace(target)
                    published = True
                except Exception:
                    if previous.exists():
                        previous.replace(target)
                    raise
            finally:
                shutil.rmtree(stage, ignore_errors=True)
                if published:
                    shutil.rmtree(previous, ignore_errors=True)
            return self.view()

    @staticmethod
    def _loader_path(name):
        prefix = 'BepInExPack_Valheim/'
        if not name.startswith(prefix):
            return None
        name = name[len(prefix):]
        if name.startswith('BepInEx/core/') or name in ('doorstop_libs/libdoorstop_x64.so', 'winhttp.dll', 'doorstop_config.ini'):
            return name
        return None

    def _prepare_loader(self, refresh=False):
        if self.state.get('loader') and not refresh:
            return self.state['loader']
        metadata = self._metadata(LOADER_ID)
        if not metadata['version_number'].startswith('5.4.'):
            raise ValueError('Поддерживается загрузчик BepInEx версии 5.4')
        if self.state.get('loader', {}) and self.state['loader']['version'] == metadata['version_number']:
            return self.state['loader']
        stored, manifest = self._store(_fetch(metadata['download_url']), self._loader_path, loader=True)
        required = {'BepInEx/core/BepInEx.Preloader.dll', 'BepInEx/core/BepInEx.dll', 'doorstop_libs/libdoorstop_x64.so', 'winhttp.dll', 'doorstop_config.ini'}
        if not required <= {entry['path'] for entry in stored['files']}:
            shutil.rmtree(self.root / 'packages' / stored['storage'])
            raise ValueError('Пакет BepInEx не содержит полный runtime Linux и Windows')
        loader = {'version': metadata['version_number'], **stored}
        proposed = copy.deepcopy(self.state)
        proposed['loader'] = loader
        try:
            self._publish(proposed)
        except Exception:
            shutil.rmtree(self.root / 'packages' / stored['storage'], ignore_errors=True)
            raise
        return loader

    def ensure_loader(self, folder, refresh=False):
        with self.lock:
            loader = self._prepare_loader(refresh=refresh)
            folder = Path(folder).resolve()
            for path, data in self._stored_files(loader):
                if not (path.startswith('BepInEx/core/') or path == 'doorstop_libs/libdoorstop_x64.so'):
                    continue
                self._release_dir(folder, str(PurePosixPath(path).parent))
                target = folder / path
                if target.is_symlink() or target.exists() and not target.is_file():
                    raise ValueError('Файл загрузчика не должен быть ссылкой или каталогом')
                temporary = target.with_name('.hearth-loader-' + uuid.uuid4().hex)
                try:
                    temporary.write_bytes(data)
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
            return {'version': loader['version'], 'unix_ready': True, 'windows_ready': True}

    def client_archive(self, include_loader=False):
        with self.lock:
            if type(include_loader) is not bool:
                raise ValueError('include_loader должен быть логическим значением')
            packages = [package for package in self.state['packages'] if package['enabled'] and package['scope'] in ('client', 'both')]
            if not packages and not include_loader:
                return None
            self._validate_graph(self.state['packages'])
            loader = self._prepare_loader() if include_loader else None
            target = self.root / ('client-full.zip' if include_loader else 'client-overlay.zip')
            temporary = self.root / ('.client-' + uuid.uuid4().hex + '.zip')
            def put(archive, path, data):
                info = zipfile.ZipInfo(path, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, data)
            try:
                with zipfile.ZipFile(temporary, 'w') as archive:
                    if loader:
                        for path, data in self._stored_files(loader):
                            if path.startswith('BepInEx/core/') or path in ('winhttp.dll', 'doorstop_config.ini'):
                                put(archive, path, data)
                    for package in packages:
                        for path, data in self._stored_files(package):
                            put(archive, 'BepInEx/plugins/HearthMods/' + package['id'] + '/' + path, data)
                    public = {'schema': 1, 'kind': 'full' if loader else 'overlay', 'revision': self.state['revision'],
                              'loader_version': loader['version'] if loader else None,
                              'packages': [_public(package) for package in packages]}
                    put(archive, 'hearth-mods.json', json.dumps(public, ensure_ascii=False, sort_keys=True).encode('utf-8'))
                with zipfile.ZipFile(temporary) as completed:
                    if (temporary.stat().st_size > MAX_ARCHIVE or len(completed.infolist()) > MAX_CLIENT_FILES
                            or sum(entry.file_size for entry in completed.infolist()) > MAX_TRANSACTION):
                        raise ValueError('Клиентский набор превышает ограничения установщика: 128 МиБ ZIP, 512 МиБ после распаковки или 5000 файлов')
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            return target
