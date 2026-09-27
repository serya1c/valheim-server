"""Valheim control panel. One process owns all mutations; no Docker socket."""
import collections
import contextlib
import hashlib
import hmac
import html
import http.cookies
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import sqlite3
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.request
from urllib.parse import urlsplit
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from configuration import Configuration, atomic_text

BASE = Path(os.getenv('DATA_DIR', '/data'))
PINNED_SHA = '4f990653dba255cacd13f60c08fc17dc0cde0fb90f200743ecb90593d34070c2'
VERSION = re.compile(r'\d+\.\d+\.\d+(?:\.\d+)?')
GAME_LOG_VERSION = re.compile(r'Valheim version:\s*(?:[A-Za-z]-)?(\d+\.\d+\.\d+)')
JOIN = re.compile(r'Got character ZDOID from (.+?) :')
CONNECTION = re.compile(r'Got connection|Got character ZDOID|Closing socket|Disconnected|New connection', re.I)
ACTION_NAMES = {'start': 'Запуск', 'stop': 'Остановка', 'restart': 'Перезапуск',
                'backup': 'Резервная копия', 'scheduled': 'Плановая копия',
                'install': 'Установка обновления', 'restore': 'Восстановление мира', 'rollback': 'Полный откат',
                'configure':'Сохранение настроек'}


def atomic_json(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def safe_unzip(archive, target):
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist()) > 512 * 1024 * 1024:
            raise ValueError('Слишком большой архив мода')
        for i in z.infolist():
            p = (target / i.filename).resolve()
            if not p.is_relative_to(target.resolve()) or stat.S_ISLNK(i.external_attr >> 16):
                raise ValueError('Небезопасный путь в архиве')
        z.extractall(target)


def fetch(url, target=None):
    req = urllib.request.Request(url, headers={'User-Agent': 'Valheim-Hearth/1.0', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=60) as response:
        if target:
            with open(target, 'wb') as f:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 256 * 1024 * 1024:
                        raise ValueError('Превышен размер загрузки')
                    f.write(chunk)
        else:
            return json.load(response)


class Store:
    def __init__(self, path):
        self.path = path
        with self.db() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts REAL, kind TEXT, message TEXT);
            CREATE TABLE IF NOT EXISTS players(name TEXT PRIMARY KEY, joins INTEGER DEFAULT 0,
              seconds REAL DEFAULT 0, last_seen REAL);
            ''')

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=20)
        try:
            with db:
                yield db
        finally:
            db.close()

    def event(self, kind, message):
        with self.db() as db:
            db.execute('INSERT INTO events(ts,kind,message) VALUES(?,?,?)', (time.time(), kind, message[:2000]))
            db.execute('DELETE FROM events WHERE id < (SELECT MAX(id)-50000 FROM events)')

    def join(self, name):
        with self.db() as db:
            db.execute('INSERT INTO players(name,joins,last_seen) VALUES(?,1,?) ON CONFLICT(name) DO UPDATE SET joins=joins+1,last_seen=excluded.last_seen', (name[:200], time.time()))

    def tick(self, names, seconds):
        with self.db() as db:
            for name in names:
                db.execute('INSERT INTO players(name,seconds,last_seen) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET seconds=seconds+excluded.seconds,last_seen=excluded.last_seen', (name[:200], seconds, time.time()))

    def read(self):
        with self.db() as db:
            db.row_factory = sqlite3.Row
            return {
                'events': [dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 150')],
                'players': [dict(r) for r in db.execute('SELECT * FROM players ORDER BY seconds DESC LIMIT 300')],
            }


class Manager:
    def __init__(self, base=BASE):
        self.base = base
        for folder in ('releases', 'saves', 'config', 'backups', 'logs'):
            (base / folder).mkdir(parents=True, exist_ok=True)
        self.store = Store(base / 'panel.sqlite')
        self.config = Configuration(base)
        self.secret_values = {os.getenv('SERVER_PASSWORD'), os.getenv('PANEL_PASSWORD'), self.config.load()['server']['password']}
        self.lock = threading.Lock()
        self.proc = None
        self.reader = None
        self.busy = False
        self.closing = False
        self.online = None
        self.last_poll = None
        self.last_names = set()
        self.job = {'state': 'idle', 'message': 'Готово'}
        self.tail = collections.deque(maxlen=500)
        self.log = logging.getLogger('valheim.' + str(id(self)))
        self.log.setLevel(logging.INFO)
        handler = RotatingFileHandler(base / 'logs/server.log', maxBytes=10_000_000, backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        self.log.addHandler(handler)
        self.state_path = base / 'state.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {'active': None, 'previous': None}
        self.started = time.time()

    def say(self, line):
        # The game may echo command-line arguments on error.
        for secret in (*tuple(self.secret_values), os.getenv('SERVER_PASSWORD'), os.getenv('PANEL_PASSWORD')):
            if secret:
                line = line.replace(secret, '[REDACTED]')
        self.log.info(line)
        self.tail.append(line[-3000:])

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def active(self):
        if not self.state.get('active'):
            raise ValueError('Сначала установите сервер')
        return self.base / 'releases' / self.state['active']

    def metadata(self):
        try:
            return json.loads((self.active() / 'hearth.json').read_text())
        except (ValueError, FileNotFoundError):
            return None

    def save_state(self):
        atomic_json(self.state_path, self.state)

    def spawn(self, folder, save_dir, port, probe=False):
        env = os.environ.copy()
        # Do not pass the panel credential to the game process.
        env.pop('PANEL_PASSWORD', None)
        env.update(SteamAppId='892970', DOORSTOP_ENABLED='1',
                   DOORSTOP_TARGET_ASSEMBLY=str(folder / 'BepInEx/core/BepInEx.Preloader.dll'),
                   LD_LIBRARY_PATH=f'{folder}/linux64:{folder}/doorstop_libs',
                   LD_PRELOAD=str(folder / 'doorstop_libs/libdoorstop_x64.so'))
        exe = folder / 'valheim_server.x86_64'
        exe.chmod(exe.stat().st_mode | 0o111)
        args = ['-name','Hearth version probe','-world','VersionProbe','-password',secrets.token_hex(12),'-public','0'] if probe else self.config.launch_args()
        return subprocess.Popen([str(exe), '-nographics', '-batchmode', '-port', str(port),
            *args, '-savedir', str(save_dir), '-logFile', '-'], cwd=folder, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace',
            start_new_session=True, bufsize=1)

    @staticmethod
    def halt(proc):
        if proc.poll() is not None:
            return
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            # Never copy or replace a world while a hung process is still writing it.
            raise RuntimeError('Сервер не завершился за 120 секунд; операция отменена. Проверьте лог.')

    def start(self):
        if self.closing or self.running():
            return
        folder = self.active()
        config = folder / 'BepInEx/config'
        if not config.is_symlink():
            if config.exists():
                for source in config.rglob('*'):
                    dest = self.base / 'config' / source.relative_to(config)
                    if source.is_file() and not dest.exists():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, dest)
                shutil.rmtree(config)
            config.symlink_to(self.base / 'config', target_is_directory=True)
        self.proc = self.spawn(folder, self.base / 'saves', 2456)
        self.started = time.time()
        self.reader = threading.Thread(target=self.read_game, args=(self.proc,), daemon=True)
        self.reader.start()
        self.store.event('system', 'Запущен процесс сервера; готовность смотрите по A2S и логу')

    def read_game(self, proc):
        for line in proc.stdout:
            line = line.rstrip()
            self.say(line)
            if CONNECTION.search(line):
                self.store.event('connection', line)
            match = JOIN.search(line)
            if match:
                self.store.join(match[1])
        self.online = None
        self.last_names.clear()
        self.last_poll = None
        self.store.event('system', f'Процесс сервера завершён, код {proc.wait()}')

    def stop(self):
        if self.running():
            self.halt(self.proc)
        if self.reader:
            self.reader.join(timeout=5)
        self.online = None
        self.last_poll = None
        self.last_names.clear()

    def backup(self, label='manual'):
        if self.running():
            raise RuntimeError('Для согласованной копии сервер должен быть остановлен')
        name = time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3) + '-' + label + '.tar.gz'
        path = self.base / 'backups' / name
        with tarfile.open(str(path) + '.tmp', 'w:gz') as tar:
            tar.add(self.base / 'saves', arcname='saves')
            tar.add(self.base / 'config', arcname='config')
            with tempfile.TemporaryDirectory(dir=self.base) as tmp:
                p = Path(tmp) / 'manifest.json'
                atomic_json(p, {'release': self.state.get('active'), 'versions': self.metadata(), 'created': time.time()})
                tar.add(p, arcname='manifest.json')
        Path(str(path) + '.tmp').replace(path)
        self.store.event('backup', name)
        return name

    def prune_backups(self):
        # Keep all manual and pre-update/restore backups; rotate scheduled backups only.
        files = sorted((self.base / 'backups').glob('*-scheduled.tar.gz'), reverse=True)
        for p in files[max(1, int(os.getenv('BACKUP_KEEP', '12'))):]:
            p.unlink()

    def latest_release(self):
        release = fetch('https://api.github.com/repos/Grantapher/ValheimPlus/releases/latest')
        mod = release.get('tag_name', '')
        if not VERSION.fullmatch(mod):
            raise ValueError('Не удалось определить версию последнего релиза Valheim Plus')
        if release.get('draft') or release.get('prerelease'):
            raise ValueError('Предварительные релизы не поддерживаются')
        body = release.get('body') or ''
        compatibility = re.search(r'^#+\s+Compatibility\s*\r?\n(.*?)(?=^#+\s|\Z)', body, re.M | re.S | re.I)
        versions = set(re.findall(r'\bValheim\s+(\d+\.\d+\.\d+)(?![\d.])', compatibility[1] if compatibility else body))
        if len(versions) != 1:
            raise ValueError('Не удалось однозначно определить совместимость последнего мода с Valheim; рабочий сервер не изменён')
        return versions.pop(), mod, release

    def install(self):
        self.job['message'] = 'Поиск последнего стабильного релиза Valheim Plus'
        game, mod, release = self.latest_release()
        self.say(f'Последний V+ {mod}; заявленная совместимость: Valheim {game}. Загружается текущий сервер Steam.')
        asset = next((a for a in release.get('assets', []) if a['name'] == 'UnixServer.zip'), None)
        if asset is None:
            raise ValueError('В последнем релизе мода отсутствует UnixServer.zip')
        digest = PINNED_SHA if mod == '0.10.2.0' else (asset.get('digest') or '').removeprefix('sha256:')
        if not re.fullmatch('[a-f0-9]{64}', digest):
            raise ValueError('У релиза отсутствует SHA-256; установка отменена')
        release_id = f'{game}-{mod}-{secrets.token_hex(4)}'
        stage = self.base / 'releases' / release_id
        stage.mkdir()
        installed = False
        try:
            self.job['message'] = 'Загрузка сервера Steam в отдельный каталог'
            self.say(self.job['message'])
            cmd = ['/opt/steamcmd/steamcmd.sh', '+force_install_dir', str(stage), '+login', 'anonymous',
                   '+app_info_update', '1', '+app_update', '896660', 'validate', '+quit']
            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, errors='replace') as p:
                timer = threading.Timer(2400, p.kill)
                timer.start()
                try:
                    for line in p.stdout:
                        self.say('[SteamCMD] ' + line.rstrip())
                    if p.wait() != 0:
                        raise RuntimeError('SteamCMD завершился с ошибкой; см. лог')
                finally:
                    timer.cancel()
            self.job['message'] = 'Загрузка и проверка Valheim Plus'
            archive = stage / 'mod.zip'
            url = asset['browser_download_url']
            if not url.startswith(f'https://github.com/Grantapher/ValheimPlus/releases/download/{mod}/'):
                raise ValueError('Неожиданный адрес релиза')
            fetch(url, archive)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
                raise ValueError('SHA-256 мода не совпадает')
            safe_unzip(archive, stage)
            archive.unlink()
            if self.closing:
                raise RuntimeError('Установка отменена: контейнер останавливается')
            self.probe(stage, game, mod)
            if self.closing:
                raise RuntimeError('Установка отменена: контейнер останавливается')
            atomic_json(stage / 'hearth.json', {'game': game, 'mod': mod, 'mod_sha256': digest, 'installed': time.time()})
            was_running = self.running()
            self.stop()
            try:
                snapshot = self.backup('pre-update')
            except Exception:
                if was_running:
                    self.start()
                raise
            old = self.state.get('active')
            old_state = self.state.copy()
            self.state.update(active=release_id, previous=old, rollback_backup=snapshot)
            try:
                self.save_state()
            except Exception:
                self.state = old_state
                if was_running:
                    self.start()
                raise
            installed = True
            self.start()
            self.store.event('update', f'Установлены Valheim {game} и V+ {mod}; предыдущий релиз сохранён')
        finally:
            if not installed:
                shutil.rmtree(stage)

    def probe(self, stage, game, mod):
        self.job['message'] = 'Проверка реальной версии на временном мире (до 180 секунд)'
        with tempfile.TemporaryDirectory(prefix='probe-', dir=self.base) as tmp:
            p = self.spawn(stage, Path(tmp), 2466, probe=True)
            markers = {}
            done = threading.Event()
            def read():
                for line in p.stdout:
                    self.say('[probe] ' + line.rstrip())
                    m = GAME_LOG_VERSION.search(line)
                    if m:
                        markers['game'] = m[1]
                    m = re.search(r'Loading \[Valheim Plus ([\d.]+)\]', line)
                    if m:
                        markers['mod'] = m[1]
                    if 'BepInEx 5.' in line:
                        markers['bepinex'] = True
                    if len(markers) == 3:
                        done.set()
                done.set()
            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            try:
                done.wait(180)
                if markers.get('game') != game or markers.get('mod') != mod or not markers.get('bepinex'):
                    raise RuntimeError(f'Последние сервер и мод не прошли проверку совместимости: {markers}. Ожидались Valheim {game} и V+ {mod}. Рабочий сервер не изменён; повторите обновление после выхода совместимого мода.')
            finally:
                try:
                    self.halt(p)
                except RuntimeError:
                    # Only the disposable probe world may be force-killed.
                    p.kill()
                    p.wait()
                reader.join(timeout=5)

    def restore(self, name, rollback=False):
        if not re.fullmatch(r'[a-zA-Z0-9.-]+\.tar\.gz', name):
            raise ValueError('Неверное имя копии')
        path = self.base / 'backups' / name
        with tempfile.TemporaryDirectory(prefix='restore-', dir=self.base) as tmp:
            target = Path(tmp)
            with tarfile.open(path, 'r:gz') as tar:
                for m in tar.getmembers():
                    if m.issym() or m.islnk() or not (m.isfile() or m.isdir()) or not (target / m.name).resolve().is_relative_to(target.resolve()):
                        raise ValueError('Небезопасная резервная копия')
                tar.extractall(target, filter='data')
            meta = json.loads((target / 'manifest.json').read_text())
            if not (target / 'saves').is_dir() or not (target / 'config').is_dir():
                raise ValueError('Неполная копия')
            release_id = meta.get('release')
            if not rollback and release_id != self.state.get('active'):
                raise ValueError('Копия от другого релиза. Для обновления используйте полный откат.')
            if rollback and (not release_id or release_id != self.state.get('previous') or not (self.base / 'releases' / release_id).is_dir()):
                raise ValueError('Предыдущий релиз недоступен')
            self.stop()
            self.backup('pre-restore')
            # Keep old directories intact until both replacements have succeeded.
            moved = []
            try:
                for folder in ('saves', 'config'):
                    old = target / (folder + '-old')
                    (self.base / folder).rename(old)
                    moved.append((folder, old))
                    (target / folder).rename(self.base / folder)
                if rollback:
                    self.state.update(active=release_id, previous=None, rollback_backup=None)
                    self.save_state()
            except Exception:
                for folder, old in reversed(moved):
                    if (self.base / folder).exists():
                        shutil.rmtree(self.base / folder)
                    old.rename(self.base / folder)
                raise
        self.store.event('restore', name)
        self.start()

    def submit(self, action, data=None):
        if self.closing or not self.lock.acquire(blocking=False):
            raise ValueError('Другая операция уже выполняется')
        self.busy = True
        self.job = {'state': 'running', 'message': ACTION_NAMES.get(action, action)}
        def work():
            try:
                self.execute(action, data or {})
                self.job = {'state': 'done', 'message': 'Операция завершена'}
            except Exception as e:
                self.say(str(e))
                self.store.event('error', str(e))
                self.job = {'state': 'error', 'message': str(e)}
            finally:
                self.busy = False
                self.lock.release()
        threading.Thread(target=work, daemon=True).start()

    def execute(self, action, data):
        self.store.event('action', ACTION_NAMES.get(action, action))
        if action == 'start':
            self.start()
        elif action == 'stop':
            self.stop()
        elif action == 'restart':
            self.stop()
            self.start()
        elif action in ('backup', 'scheduled'):
            was_running = self.running()
            self.stop()
            try:
                self.backup('scheduled' if action == 'scheduled' else 'manual')
                self.prune_backups()
            finally:
                if was_running:
                    self.start()
        elif action == 'install':
            self.install()
        elif action == 'restore':
            self.restore(data.get('name', ''))
        elif action == 'rollback':
            self.restore(self.state.get('rollback_backup') or '', rollback=True)
        elif action == 'configure':
            self.configure(data)
        else:
            raise ValueError('Неизвестная операция')

    def configure(self, data):
        if type(data.get('restart')) is not bool:
            raise ValueError('Выберите способ применения настроек')
        path, content = self.config.prepare(data)  # Validate before interrupting players.
        if data.get('scope') == 'landing':
            atomic_json(path.with_name('hearth-settings.previous.json'), self.config.load())
            atomic_text(path, content)
            self.store.event('config', 'Обновлена публичная страница сервера')
            return
        was_running = self.running()
        self.stop()
        try:
            path, content = self.config.prepare(data)  # Detect external edits during shutdown.
            self.backup('pre-config')
            atomic_text(path, content)
            self.secret_values.add(self.config.load()['server']['password'])
        except Exception:
            if was_running:
                self.start()
            raise
        self.store.event('config', 'Сохранены настройки: ' + {'server':'сервер','world':'мир','mod':'Valheim Plus'}[data['scope']])
        if data['restart'] and self.state.get('active'):
            self.start()

    def poll(self):
        next_backup = time.time() + float(os.getenv('BACKUP_HOURS', '6')) * 3600
        while not self.closing:
            try:
                if self.running():
                    import a2s
                    info = a2s.info(('127.0.0.1', 2457), timeout=2)
                    names = []
                    try:
                        names = [p.name for p in a2s.players(('127.0.0.1', 2457), timeout=2) if p.name]
                    except Exception:
                        pass
                    now = time.time()
                    if self.last_poll is not None:
                        self.store.tick(set(names) & self.last_names, min(20, now - self.last_poll))
                    self.last_poll = now
                    self.last_names = set(names)
                    self.online = {'count': info.player_count, 'names': names, 'version': info.version, 'at': now}
                else:
                    self.online = None
                    self.last_poll = None
                    self.last_names.clear()
            except Exception:
                self.online = None
                self.last_poll = None
                self.last_names.clear()
            interval = float(os.getenv('BACKUP_HOURS', '6')) * 3600
            if interval > 0 and time.time() >= next_backup:
                # Never interrupt players or assume a failed query means an empty server.
                if not self.busy and (not self.running() or self.online is not None and self.online['count'] == 0):
                    with contextlib.suppress(ValueError):
                        self.submit('scheduled')
                    next_backup = time.time() + interval
            time.sleep(10)

    def status(self):
        files = []
        for p in (self.base / 'saves').rglob('*'):
            if p.is_file():
                s = p.stat()
                files.append({'path': str(p.relative_to(self.base / 'saves')), 'bytes': s.st_size, 'modified': s.st_mtime})
        backups = [{'name': p.name, 'bytes': p.stat().st_size} for p in sorted((self.base / 'backups').glob('*.tar.gz'), reverse=True)]
        return {**self.store.read(), 'running': self.running(), 'busy': self.busy,
            'job': self.job, 'versions': self.metadata(), 'online': self.online,
            'uptime': time.time() - self.started if self.running() else 0,
            'world': self.config.load()['world_name'], 'files': files[:1000],
            'free_bytes': shutil.disk_usage(self.base).free, 'backups': backups,
            'rollback': bool(self.state.get('previous')), 'logs': list(self.tail)[-180:]}


class Handler(BaseHTTPRequestHandler):
    manager = None
    password = ''
    sessions = {}
    attempts = collections.deque(maxlen=100)
    auth_lock = threading.Lock()

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *args):
        pass

    def reply(self, status, body, content_type='application/json; charset=utf-8', cookie=None):
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        if self.path.startswith(('/admin', '/api/', '/health')):
            self.send_header('X-Robots-Tag', 'noindex, nofollow')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(raw)

    def session(self):
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
        except http.cookies.CookieError:
            return None
        token = cookie['session'].value if 'session' in cookie else ''
        with self.auth_lock:
            s = self.sessions.get(token)
            return s if s and s['expires'] > time.time() else None

    def do_GET(self):
        self.path = urlsplit(self.path).path
        if self.path in {'/downloads/Loki-Mod-Installer.exe', '/downloads/Loki-Mod-Installer.exe.sha256',
                         '/downloads/Loki-Mod-Installer-Linux.sh', '/downloads/Loki-Mod-Installer-Linux.sh.sha256'}:
            name = self.path.rsplit('/', 1)[1]
            path = Path(__file__).parent / 'downloads' / name
            if not path.is_file():
                return self.reply(404, {'error': 'Установщик ещё не опубликован'})
            with path.open('rb') as source:
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(path.stat().st_size))
                self.send_header('Content-Disposition', f'attachment; filename="{name}"')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('X-Robots-Tag', 'noindex, nofollow')
                self.end_headers()
                shutil.copyfileobj(source, self.wfile)
            return
        if self.path == '/robots.txt':
            return self.reply(200, b'User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /health\nSitemap: https://loki.ach-play.ru/sitemap.xml\n', 'text/plain; charset=utf-8')
        if self.path == '/sitemap.xml':
            return self.reply(200, b'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://loki.ach-play.ru/</loc></url></urlset>', 'application/xml; charset=utf-8')
        if self.path == '/health':
            return self.reply(200, {'panel': 'ok'})
        if self.path == '/api/public':
            config = self.manager.config.load()
            landing = config['landing']
            versions = self.manager.metadata() or {}
            running = self.manager.running()
            online = self.manager.online
            fresh = running and online and time.time() - online.get('at', 0) < 30
            return self.reply(200, {'title':landing['title'] or config['server']['name'],
                'server_name':self.manager.config.advertised_name(),
                'description':landing['description'], 'address':landing['address'],
                'community_url':landing['community_url'], 'running':running,
                'players':online['count'] if fresh else None,
                'game':versions.get('game'), 'mod':versions.get('mod')})
        assets = {'/': ('landing.html', 'text/html; charset=utf-8'), '/admin': ('index.html', 'text/html; charset=utf-8'), '/admin/': ('index.html', 'text/html; charset=utf-8'), '/landing.css': ('landing.css', 'text/css; charset=utf-8'), '/landing.js': ('landing.js', 'text/javascript; charset=utf-8'), '/north.svg': ('north.svg', 'image/svg+xml'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/settings.js': ('settings.js', 'text/javascript; charset=utf-8'), '/mod-ru.js': ('mod-ru.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if self.path in assets:
            name, mime = assets[self.path]
            if name == 'landing.html':
                config = self.manager.config.load()
                landing = config['landing']
                values = {'SITE_TITLE':landing['title'] or config['server']['name'],
                    'SITE_DESCRIPTION':landing['description'],
                    'SERVER_ADDRESS':landing['address'] or 'Адрес скоро появится',
                    'LISTING_NAME':self.manager.config.advertised_name()}
                template = (Path(__file__).parent / 'static' / name).read_text(encoding='utf-8-sig')
                body = re.sub(r'\{\{(SITE_TITLE|SITE_DESCRIPTION|SERVER_ADDRESS|LISTING_NAME)\}\}', lambda m: html.escape(values[m[1]], quote=True), template)
                return self.reply(200, body.encode(), mime)
            return self.reply(200, (Path(__file__).parent / 'static' / name).read_bytes(), mime)
        session = self.session()
        if not session:
            return self.reply(401, {'error': 'Войдите в панель'})
        if self.path == '/api/session':
            return self.reply(200, {'csrf': session['csrf']})
        if self.path == '/api/status':
            return self.reply(200, self.manager.status())
        if self.path == '/api/config':
            try:
                return self.reply(200, self.manager.config.view())
            except ValueError as e:
                return self.reply(400, {'error':str(e)})
        if self.path.startswith('/api/backup/'):
            name = self.path.removeprefix('/api/backup/')
            if not re.fullmatch(r'[a-zA-Z0-9.-]+\.tar\.gz', name):
                return self.reply(400, {'error': 'Неверное имя'})
            path = self.manager.base / 'backups' / name
            if not path.is_file():
                return self.reply(404, {'error': 'Копия не найдена'})
            self.send_response(200)
            self.send_header('Content-Type', 'application/gzip')
            self.send_header('Content-Length', str(path.stat().st_size))
            self.send_header('Content-Disposition', f'attachment; filename="{name}"')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            with path.open('rb') as f:
                shutil.copyfileobj(f, self.wfile)
            return
        return self.reply(404, {'error': 'Не найдено'})

    def do_POST(self):
        # Non-simple header forces a same-origin request; no CORS is enabled.
        if self.headers.get('X-Hearth') != '1' or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply(403, {'error': 'Недопустимый запрос'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            limit = 262144 if self.path == '/api/action' else 4096
            if not 0 < length <= limit:
                raise ValueError('Недопустимый размер запроса')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Ожидается объект JSON')
            if self.path == '/api/login':
                with self.auth_lock:
                    now = time.time()
                    while self.attempts and self.attempts[0] < now - 60:
                        self.attempts.popleft()
                    if len(self.attempts) >= 10:
                        return self.reply(429, {'error': 'Слишком много попыток. Подождите минуту.'})
                    self.attempts.append(now)
                    supplied = str(data.get('password', '')).encode()
                    if not hmac.compare_digest(supplied, self.password.encode()):
                        return self.reply(401, {'error': 'Неверный пароль'})
                    expired = [k for k, v in self.sessions.items() if v['expires'] < now]
                    for k in expired:
                        del self.sessions[k]
                    if len(self.sessions) >= 100:
                        del self.sessions[next(iter(self.sessions))]
                    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                    self.sessions[token] = {'expires': now + 28800, 'csrf': csrf}
                secure = '; Secure' if os.getenv('COOKIE_SECURE') == '1' else ''
                return self.reply(200, {'csrf': csrf}, cookie=f'session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800{secure}')
            session = self.session()
            if not session or not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), session['csrf']):
                return self.reply(403, {'error': 'Сессия истекла. Войдите снова.'})
            if self.path == '/api/logout':
                with self.auth_lock:
                    for k, v in list(self.sessions.items()):
                        if v is session:
                            del self.sessions[k]
                return self.reply(200, {}, cookie='session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            if self.path == '/api/action':
                action = data.get('action')
                if action not in {'start', 'stop', 'restart', 'backup', 'install', 'restore', 'rollback', 'configure'}:
                    raise ValueError('Неизвестная операция')
                self.manager.submit(action, data)
                return self.reply(202, {'accepted': True})
            return self.reply(404, {'error': 'Не найдено'})
        except (ValueError, TypeError) as e:
            return self.reply(400, {'error': str(e)})


def main():
    password = os.getenv('PANEL_PASSWORD', '')
    game_password = os.getenv('SERVER_PASSWORD', '')
    if len(password) < 16 or 'CHANGE_ME' in password or len(game_password) < 5 or 'CHANGE_ME' in game_password:
        raise SystemExit('Укажите PANEL_PASSWORD (16+ символов) и SERVER_PASSWORD (5+ символов) в .env')
    if game_password.lower() in os.getenv('SERVER_NAME', 'Loki').lower():
        raise SystemExit('Пароль игры не должен входить в название сервера')
    if not re.fullmatch(r'[\w -]{1,80}', os.getenv('WORLD_NAME', 'North')):
        raise SystemExit('WORLD_NAME: используйте буквы, цифры, пробел, дефис или подчёркивание')
    os.umask(0o077)
    manager = Manager()
    Handler.manager, Handler.password = manager, password
    httpd = ThreadingHTTPServer(('0.0.0.0', 8080), Handler)
    def shutdown(*_):
        manager.closing = True
        def finish():
            # Save the live world even if SteamCMD currently holds the operation lock.
            with contextlib.suppress(Exception):
                manager.stop()
            with manager.lock:
                with contextlib.suppress(Exception):
                    manager.stop()
            httpd.shutdown()
        threading.Thread(target=finish, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    threading.Thread(target=manager.poll, daemon=True).start()
    if manager.state.get('active'):
        manager.submit('start')
    else:
        manager.submit('install')
    httpd.serve_forever()
    httpd.server_close()


if __name__ == '__main__':
    main()
