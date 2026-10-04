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
from configuration import Configuration, atomic_text, game_ports, server_mode, listing_required, default_world
from panel import Panel, password_hash
import world_transfer
from operations import Operations
from player_access import PlayerAccess, LABELS as PLAYER_ACTION_NAMES, steam_id

BASE = Path(os.getenv('DATA_DIR', '/data'))
PINNED_SHA = '4f990653dba255cacd13f60c08fc17dc0cde0fb90f200743ecb90593d34070c2'
VERSION = re.compile(r'\d+\.\d+\.\d+(?:\.\d+)?')
GAME_LOG_VERSION = re.compile(r'Valheim version:\s*(?:[A-Za-z]-)?(\d+\.\d+\.\d+)')
STARTUP_ERROR = re.compile(r'HarmonyException|MissingMethodException|MissingFieldException|TypeLoadException|\[(?:Error|Fatal)\s*:\s*(?:Valheim Plus|BepInEx)\s*\]', re.I)


class CompatibilityApprovalRequired(RuntimeError):
    def __init__(self, actual):
        self.actual = actual
        super().__init__('Нужно одобрение другой версии игры: ' + actual)


def observe_startup(markers, line):
    match = GAME_LOG_VERSION.search(line)
    if match:
        markers['game'] = match[1]
    match = re.search(r'Loading \[Valheim Plus ([\d.]+)\]', line)
    if match:
        markers['mod'] = match[1]
    if 'BepInEx 5.' in line:
        markers['bepinex'] = True
    if 'Game server connected' in line:
        markers['ready'] = True
    if STARTUP_ERROR.search(line):
        markers['error'] = line[-1000:]


JOIN = re.compile(r'Got character ZDOID from (.+?) :')
CONNECTION = re.compile(r'Got connection|Got character ZDOID|Closing socket|Disconnected|New connection', re.I)
ACTION_NAMES = {'start': 'Запуск', 'stop': 'Остановка', 'restart': 'Перезапуск',
                'backup': 'Резервная копия', 'scheduled': 'Плановая копия',
                'install': 'Установка обновления', 'restore': 'Восстановление мира', 'rollback': 'Полный откат',
                'configure':'Сохранение настроек', 'export_world':'Экспорт мира', 'import_world':'Импорт мира',
                'maintenance':'Обслуживание', 'check_panel':'Проверка версии панели'}


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
        self.panel = Panel(base)
        self.setup_token = secrets.token_urlsafe(32)
        self.secret_values = {os.getenv('SERVER_PASSWORD'), os.getenv('PANEL_PASSWORD'), self.config.load()['server']['password']}
        self.lock = threading.Lock()
        self.proc = None
        self.startup = {}
        self.compatibility = None
        self.pending_import = None
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
        self.maintenance_wait_empty = False
        self.operations = Operations(self)
        self.player_access = PlayerAccess(self)

    def setup_view(self):
        view = self.config.view()
        if not self.config.path.exists() and not self.state.get('active'):
            view['server'].update(name='Valheim', mode='plus', public=True, add_site=True, password_set=False)
            view['landing'].update(title='Valheim', site_url='http://localhost:8080', address='', community_url='')
        return {'csrf': self.setup_token, 'existing': bool(self.state.get('active')), 'config': view, 'panel': self.panel.view()}

    def complete_setup(self, data):
        with self.lock:
            if self.panel.configured:
                raise ValueError('Первичная настройка уже завершена')
            if self.closing:
                raise ValueError('Панель останавливается')
            if set(data) != {'panel_password', 'panel', 'server', 'world', 'landing'}:
                raise ValueError('Неполные настройки первого запуска')
            panel = {**Panel.validate(data['panel']), 'auth': password_hash(data['panel_password'])}
            # Validate everything in isolation before changing the real configuration.
            with tempfile.TemporaryDirectory(dir=self.base) as tmp:
                target = Path(tmp)
                (target / 'config').mkdir()
                config = Configuration(target)
                atomic_json(config.path, self.config.load())
                for scope in ('server', 'world', 'landing'):
                    path, content = config.prepare({'scope': scope, 'values': data[scope], 'revision': config.revision()})
                    atomic_text(path, content)
                settings = config.load()
            if panel['cookie_secure'] and not settings['landing']['site_url'].startswith('https://'):
                raise ValueError('Для входа только по HTTPS укажите HTTPS-адрес сайта')
            previous = self.config.path.read_bytes() if self.config.path.exists() else None
            if self.state.get('active'):
                self.backup('pre-setup')
            try:
                atomic_json(self.config.path, settings)
                self.panel.save(panel)  # Commit marker; game remains stopped until this succeeds.
            except Exception:
                if previous is None:
                    self.config.path.unlink(missing_ok=True)
                else:
                    atomic_text(self.config.path, previous.decode('utf-8'))
                raise
            self.secret_values.add(settings['server']['password'])
            self.setup_token = None
            self.store.event('config', 'Первичная настройка завершена')

    def boot_action(self):
        if self.state.get('update_trial') and self.state.get('previous'):
            return 'rollback'
        return 'start' if self.state.get('active') else 'install'

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

    def spawn(self, folder, save_dir, port, probe=False, mode=None):
        env = os.environ.copy()
        # Do not pass the panel credential to the game process.
        env.pop('PANEL_PASSWORD', None)
        mode = mode or json.loads((folder / 'hearth.json').read_text()).get('mode', 'plus')
        env.update(SteamAppId='892970', LD_LIBRARY_PATH=f'{folder}/linux64')
        for key in ('LD_PRELOAD', 'DOORSTOP_ENABLED', 'DOORSTOP_TARGET_ASSEMBLY'):
            env.pop(key, None)
        if mode == 'plus':
            env.update(DOORSTOP_ENABLED='1', DOORSTOP_TARGET_ASSEMBLY=str(folder / 'BepInEx/core/BepInEx.Preloader.dll'),
                       LD_LIBRARY_PATH=f'{folder}/linux64:{folder}/doorstop_libs', LD_PRELOAD=str(folder / 'doorstop_libs/libdoorstop_x64.so'))
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
        self.player_access.cleanup(force=True)
        folder = self.active()
        config = folder / 'BepInEx/config'
        if (self.metadata() or {}).get("mode", "plus") == "plus" and not config.is_symlink():
            if config.exists():
                for source in config.rglob('*'):
                    dest = self.base / 'config' / source.relative_to(config)
                    if source.is_file() and not dest.exists():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, dest)
                shutil.rmtree(config)
            config.symlink_to(self.base / 'config', target_is_directory=True)
        self.startup = {}
        self.operations.ready = False
        self.online = None
        self.proc = self.spawn(folder, self.base / 'saves', game_ports()[0])
        self.started = time.time()
        self.reader = threading.Thread(target=self.read_game, args=(self.proc,), daemon=True)
        self.reader.start()
        self.store.event('system', 'Запущен процесс сервера; готовность смотрите по A2S и логу')

    def read_game(self, proc):
        for line in proc.stdout:
            line = line.rstrip()
            self.say(line)
            if proc is self.proc:
                observe_startup(self.startup, line)
            if CONNECTION.search(line):
                self.store.event('connection', line)
            match = JOIN.search(line)
            if match:
                self.store.join(match[1])
        self.online = None
        self.last_names.clear()
        self.last_poll = None
        code=proc.wait()
        self.store.event('system', f'Процесс сервера завершён, код {code}')
        self.operations.notify('server','Сервер остановлен.')
        if code:self.operations.notify('error','Игровой процесс завершился с ошибкой. Проверьте журнал панели.')

    def wait_ready(self, game, mod, timeout=180):
        self.job['message'] = 'Проверка запуска основного мира (до 180 секунд)'
        deadline = time.monotonic() + timeout
        stable_since = None
        while time.monotonic() < deadline:
            if self.closing or not self.running() or self.startup.get('error'):
                raise RuntimeError('Новый сервер остановился или сообщил ошибку загрузки: ' + str(self.startup))
            if self.startup.get('ready') and self.startup.get('game') == game and (mod is None or self.startup.get('mod') == mod and self.startup.get('bepinex')):
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= 5:
                    return
            time.sleep(0.25)
        raise RuntimeError('Основной мир не подтвердил готовность за отведённое время')

    def stop(self):
        if self.running():
            self.halt(self.proc)
        if self.reader:
            self.reader.join(timeout=5)
        self.online = None
        self.last_poll = None
        self.last_names.clear()
        self.player_access.cleanup(force=True)

    def backup(self, label='manual'):
        if self.running():
            raise RuntimeError('Для согласованной копии сервер должен быть остановлен')
        # Temporary kicks must never become permanent bans after restoring a backup.
        self.player_access.cleanup(force=True)
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
        for p in files[self.panel.load()['backup_keep']:]:
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

    def install(self, approval_token=None):
        approval = None
        if approval_token is not None:
            pending = self.compatibility
            if not isinstance(approval_token, str) or not pending or pending['expires'] < time.time() or not hmac.compare_digest(approval_token, pending['token']):
                raise ValueError('Одобрение устарело. Снова проверьте обновление.')
            approval = pending.copy()
        self.compatibility = None  # One attempt only; never a permanent bypass.
        mode = server_mode(self.config.load()['server']['mode'])
        if approval and mode != 'plus':
            raise ValueError('Режим изменился; повторите обновление без старого одобрения')
        game = mod = digest = None
        if mode == 'plus':
            self.job['message'] = 'Поиск последнего стабильного релиза Valheim Plus'
            game, mod, release = self.latest_release()
            self.say(f'Последний V+ {mod}; заявленная совместимость: Valheim {game}. Загружается текущий сервер Steam.')
            asset = next((a for a in release.get('assets', []) if a['name'] == 'UnixServer.zip'), None)
            if asset is None:
                raise ValueError('В последнем релизе мода отсутствует UnixServer.zip')
            digest = PINNED_SHA if mod == '0.10.2.0' else (asset.get('digest') or '').removeprefix('sha256:')
            if not re.fullmatch('[a-f0-9]{64}', digest):
                raise ValueError('У релиза отсутствует SHA-256; установка отменена')
        release_id = f'{mode}-{secrets.token_hex(8)}'
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
            if mode == 'plus':
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
            expected = game
            if approval:
                if (approval['declared'], approval['mod'], approval['sha256']) != (game, mod, digest):
                    raise ValueError('Состав обновления изменился. Нужно новое одобрение.')
                expected = approval['actual']
            try:
                probed = self.probe(stage, expected, mod)
            except CompatibilityApprovalRequired as mismatch:
                self.compatibility = {'token': secrets.token_urlsafe(32), 'declared': game,
                    'actual': mismatch.actual, 'mod': mod, 'sha256': digest, 'expires': time.time() + 1800}
                self.store.event('update', f'Ожидает одобрения: Valheim {mismatch.actual}, V+ {mod}; автор указал {game}')
                raise RuntimeError(f'Steam загрузил Valheim {mismatch.actual}, автор V+ {mod} указал {game}. Тестовый мир запустился. Одобрите эту пару во вкладке «Обновления». Рабочий сервер не изменён.') from None
            actual = probed if mode == 'vanilla' else expected
            if self.closing:
                raise RuntimeError('Установка отменена: контейнер останавливается')
            atomic_json(stage / 'hearth.json', {'mode': mode, 'game': actual, 'mod': mod, 'mod_sha256': digest, 'installed': time.time(),
                'compatibility': {'declared': game, 'approved': bool(approval), 'approved_at': time.time() if approval else None}})
            if approval:
                self.store.event('update', f'Администратор одобрил Valheim {actual} + V+ {mod}; заявлено {game}')
            was_running = self.running()
            self.guard_maintenance()
            self.stop()
            try:
                snapshot = self.backup('pre-update')
            except Exception:
                if was_running:
                    self.start()
                raise
            old = self.state.get('active')
            old_state = self.state.copy()
            self.state.update(active=release_id, previous=old, rollback_backup=snapshot, update_trial=bool(old))
            try:
                self.save_state()
            except Exception:
                self.state = old_state
                if was_running:
                    self.start()
                raise
            installed = True
            try:
                self.start()
                self.wait_ready(actual, mod)
            except Exception as error:
                self.say('Неудачный запуск обновления: ' + str(error))
                try:
                    if old:
                        self.restore(snapshot, rollback=True)
                        self.operations.notify('update','Выполнен автоматический откат обновления. Проверьте журнал панели.')
                        self.store.event('update', 'Автоматический откат: возвращены прежний релиз, мир и конфигурация')
                    else:
                        self.stop()
                except Exception as recovery_error:
                    raise RuntimeError(f'Неудачный запуск; автоматический откат не завершён: {recovery_error}. Копия: {snapshot}') from error
                raise RuntimeError('Обновление не запустилось. ' + ('Выполнен автоматический откат.' if old else 'Процесс остановлен; предыдущего релиза нет.') + ' Причина: ' + str(error)) from error
            self.state['update_trial'] = False
            self.save_state()
            self.store.event('update', f'Установлен Valheim {actual}, режим {mode}; запуск подтверждён, предыдущий релиз сохранён')
        finally:
            if not installed:
                shutil.rmtree(stage)

    def probe(self, stage, game, mod):
        self.job['message'] = 'Проверка реальной версии на временном мире (до 180 секунд)'
        with tempfile.TemporaryDirectory(prefix='probe-', dir=self.base) as tmp:
            p = self.spawn(stage, Path(tmp), 2476 if {2466, 2467}.intersection(game_ports()) else 2466, probe=True, mode='plus' if mod else 'vanilla')
            markers = {}
            done = threading.Event()
            def read():
                for line in p.stdout:
                    self.say('[probe] ' + line.rstrip())
                    observe_startup(markers, line)
                    if markers.get('ready') or markers.get('error'):
                        done.set()
                done.set()
            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            try:
                done.wait(180)
                if p.poll() is not None or markers.get('error') or not markers.get('ready') or (mod is not None and (markers.get('mod') != mod or not markers.get('bepinex'))) or not VERSION.fullmatch(markers.get('game', '')):
                    raise RuntimeError(f'Тестовый мир не прошёл проверку запуска: {markers}. Рабочий сервер не изменён.')
                if game is not None and markers['game'] != game:
                    raise CompatibilityApprovalRequired(markers['game'])
                return markers['game']
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
            with self.player_access.lock:
                moved = []
                try:
                    for folder in ('saves', 'config'):
                        old = target / (folder + '-old')
                        (self.base / folder).rename(old)
                        moved.append((folder, old))
                        (target / folder).rename(self.base / folder)
                    if rollback:
                        self.state.update(active=release_id, previous=None, rollback_backup=None, update_trial=False)
                        self.save_state()
                except Exception:
                    for folder, old in reversed(moved):
                        if (self.base / folder).exists():
                            shutil.rmtree(self.base / folder)
                        old.rename(self.base / folder)
                    raise
        self.store.event('restore', name)
        self.start()

    def guard_maintenance(self):
        if not self.maintenance_wait_empty or not self.running():return
        try:
            import a2s
            if a2s.info(('127.0.0.1', game_ports()[1]), timeout=2).player_count != 0:raise ValueError()
        except Exception:
            raise ValueError('Обслуживание отменено: сервер больше не пуст или онлайн неизвестен') from None

    def submit(self, action, data=None):
        if self.closing or not self.lock.acquire(blocking=False):
            raise ValueError('Другая операция уже выполняется')
        self.busy = True
        self.job = {'state': 'running', 'message': ACTION_NAMES.get(action, action)}
        def work():
            try:
                self.execute(action, data or {})
                self.job = {'state': 'done', 'message': 'Мир импортирован. Проверьте настройки и запустите сервер.' if action == 'import_world' else 'Операция завершена'}
            except Exception as e:
                self.operations.notify('error','Операция завершилась ошибкой. Подробности доступны администратору в журнале панели.')
                self.say(str(e))
                self.store.event('error', str(e))
                self.job = {'state': 'error', 'message': str(e)}
            finally:
                self.busy = False
                self.lock.release()
        threading.Thread(target=work, daemon=True).start()

    def execute(self, action, data):
        self.store.event('action', ACTION_NAMES.get(action, action))
        if action == 'maintenance':
            self.operations.run_pending()
        elif action == 'check_panel':
            self.operations.check_release()
        elif action == 'start':
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
            if 'approval_token' in data:
                self.install(data['approval_token'])
            else:
                self.install()
        elif action == 'restore':
            self.restore(data.get('name', ''))
        elif action == 'rollback':
            self.restore(self.state.get('rollback_backup') or '', rollback=True)
        elif action == 'export_world':
            world_transfer.export_world(self)
        elif action == 'import_world':
            world_transfer.import_world(self, data.get('token'))
        elif action == 'configure':
            self.configure(data)
        else:
            raise ValueError('Неизвестная операция')

        if action in ('install','rollback'):self.operations.notify('update','Операция обновления или отката завершена. Проверьте состояние сервера в панели.')
        if action in ('backup','scheduled'):self.operations.notify('backup','Резервная копия создана.')

    def configure(self, data):
        if type(data.get('restart')) is not bool:
            raise ValueError('Выберите способ применения настроек')
        if data.get('scope') == 'panel':
            if data.get('panel_revision') != self.panel.revision():
                raise ValueError('Настройки панели изменились; перечитайте их')
            values = dict(data.get('values', {}))
            new_password = values.pop('password', '')
            current_password = values.pop('current_password', '')
            settings = {**self.panel.load(), **Panel.validate(values)}
            if settings['cookie_secure'] and not self.config.load()['landing']['site_url'].startswith('https://'):
                raise ValueError('Сначала укажите HTTPS-адрес во вкладке лендинга')
            if new_password:
                if not self.panel.verify(current_password):
                    raise ValueError('Текущий пароль администратора неверен')
                settings['auth'] = password_hash(new_password)
            self.panel.save(settings)
            if new_password:
                with Handler.auth_lock:
                    Handler.sessions.clear()
            self.store.event('config', 'Обновлены настройки панели')
            return
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
            self.compatibility = None
            self.secret_values.add(self.config.load()['server']['password'])
        except Exception:
            if was_running:
                self.start()
            raise
        self.store.event('config', 'Сохранены настройки: ' + {'server':'сервер','world':'мир','mod':'Valheim Plus'}[data['scope']])
        if data['restart'] and self.state.get('active'):
            self.start()

    def poll(self):
        last_interval = self.panel.load()['backup_hours'] * 3600
        next_backup = time.time() + last_interval
        while not self.closing:
            try:
                if self.running():
                    import a2s
                    info = a2s.info(('127.0.0.1', game_ports()[1]), timeout=2)
                    names = []
                    try:
                        names = [p.name for p in a2s.players(('127.0.0.1', game_ports()[1]), timeout=2) if p.name]
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
            interval = self.panel.load()['backup_hours'] * 3600
            if interval != last_interval:
                next_backup = time.time() + interval
                last_interval = interval
            if self.panel.configured and interval > 0 and time.time() >= next_backup:
                # Never interrupt players or assume a failed query means an empty server.
                if not self.busy and (not self.running() or self.online is not None and self.online['count'] == 0):
                    with contextlib.suppress(ValueError):
                        self.submit('scheduled')
                    next_backup = time.time() + interval
            if self.panel.configured:
                # Expiration keeps working during a long download/probe operation.
                try:self.player_access.cleanup()
                except Exception:self.say('Не удалось снять временный бан. Проверьте списки доступа в разделе игроков.')
                try:self.operations.tick()
                except Exception:self.say('Не удалось обработать очередь обслуживания')
            time.sleep(10)

    def status(self):
        files = []
        for p in (self.base / 'saves').rglob('*'):
            if p.is_file():
                s = p.stat()
                files.append({'path': str(p.relative_to(self.base / 'saves')), 'bytes': s.st_size, 'modified': s.st_mtime})
        backups = [{'name': p.name, 'bytes': p.stat().st_size} for p in sorted((self.base / 'backups').glob('*.tar.gz'), reverse=True)]
        return {**self.store.read(), 'operations':self.operations.view(), 'player_access':self.player_access.view(),
            'running': self.running(), 'busy': self.busy, 'closing':self.closing,
            'target_mode': self.config.load()['server']['mode'], 'site_url': self.config.load()['landing']['site_url'],
            'job': self.job, 'versions': self.metadata(), 'online': self.online,
            'compatibility': self.compatibility if self.compatibility and self.compatibility['expires'] > time.time() else None,
            'uptime': time.time() - self.started if self.running() else 0,
            'world': self.config.load()['world_name'], 'files': files[:1000],
            'free_bytes': shutil.disk_usage(self.base).free, 'backups': backups,
            'exports': [{'name':p.name,'bytes':p.stat().st_size} for p in sorted((self.base/'exports').glob('world-*.zip'),reverse=True)],
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
        if not self.manager.panel.configured or self.path.startswith(('/admin', '/api/', '/health')):
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
        if self.path in ('/i18n.js','/i18n-catalog.js','/i18n.css'):
            name = self.path[1:]
            mime = 'text/css' if name.endswith('.css') else 'text/javascript'
            return self.reply(200, (Path(__file__).parent/'static'/name).read_bytes(), mime+'; charset=utf-8')
        if self.path == '/health':
            return self.reply(200, {'panel': 'ok', 'configured': self.manager.panel.configured})
        if not self.manager.panel.configured:
            if self.path == '/api/setup':
                return self.reply(200, self.manager.setup_view())
            setup_assets = {'/':('setup.html','text/html'), '/admin':('setup.html','text/html'), '/admin/':('setup.html','text/html'), '/setup':('setup.html','text/html'), '/setup.js':('setup.js','text/javascript'), '/setup.css':('setup.css','text/css')}
            if self.path in setup_assets:
                name, mime = setup_assets[self.path]
                return self.reply(200, (Path(__file__).parent / 'static' / name).read_bytes(), mime+'; charset=utf-8')
            return self.reply(409, {'error':'Сначала завершите первоначальную настройку'})
        if self.path == '/api/setup' or self.path == '/setup':
            return self.reply(409, {'error':'Первичная настройка уже завершена; войдите в /admin'})
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
        if self.path in ('/robots.txt', '/sitemap.xml'):
            site = self.manager.config.load()['landing']['site_url']
            if self.path == '/robots.txt':
                return self.reply(200, f'User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /admin\nDisallow: /health\nSitemap: {site}/sitemap.xml\n'.encode(), 'text/plain; charset=utf-8')
            return self.reply(200, ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>'+html.escape(site)+'/</loc></url></urlset>').encode(), 'application/xml; charset=utf-8')
        if self.path == '/api/public':
            config = self.manager.config.load()
            landing = config['landing']
            versions = self.manager.metadata() or {}
            running = self.manager.running()
            online = self.manager.online
            fresh = running and online and time.time() - online.get('at', 0) < 30
            return self.reply(200, {'title':landing['title'] or config['server']['name'],
                'server_name':self.manager.config.advertised_name(),
                'description':landing['description'], 'description_en':landing['description_en'], 'address':landing['address'],
                'public_listing':listing_required() or config['server']['public'], 'site_url':landing['site_url'], 'mode':versions.get('mode', 'plus' if versions else config['server']['mode']),
                'community_url':landing['community_url'], 'running':running,
                'players':online['count'] if fresh else None,
                'maintenance':self.manager.operations.view()['maintenance'],
                'game':versions.get('game'), 'mod':versions.get('mod')})
        assets = {'/': ('landing.html', 'text/html; charset=utf-8'), '/admin': ('index.html', 'text/html; charset=utf-8'), '/admin/': ('index.html', 'text/html; charset=utf-8'), '/landing.css': ('landing.css', 'text/css; charset=utf-8'), '/landing.js': ('landing.js', 'text/javascript; charset=utf-8'), '/north.svg': ('north.svg', 'image/svg+xml'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/operations.js': ('operations.js', 'text/javascript; charset=utf-8'), '/players.js': ('players.js', 'text/javascript; charset=utf-8'), '/transfer.js': ('transfer.js', 'text/javascript; charset=utf-8'), '/settings.js': ('settings.js', 'text/javascript; charset=utf-8'), '/mod-ru.js': ('mod-ru.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if self.path in assets:
            name, mime = assets[self.path]
            if name == 'landing.html':
                config = self.manager.config.load()
                landing = config['landing']
                versions = self.manager.metadata() or {}
                mode = versions.get('mode', 'plus' if versions else config['server']['mode'])
                values = {'SITE_URL':landing['site_url'], 'MODE_LABEL':'Valheim Plus' if mode == 'plus' else 'Ванильный сервер',
                    'LISTING_HIDDEN':'' if listing_required() or config['server']['public'] else 'hidden',
                    'PLUS_HIDDEN':'' if mode == 'plus' else 'hidden', 'VANILLA_HIDDEN':'hidden' if mode == 'plus' else '',
                    'SITE_TITLE':landing['title'] or config['server']['name'],
                    'SITE_DESCRIPTION':landing['description'],
                    'SERVER_ADDRESS':landing['address'] or 'Адрес скоро появится',
                    'LISTING_NAME':self.manager.config.advertised_name()}
                template = (Path(__file__).parent / 'static' / name).read_text(encoding='utf-8-sig')
                body = re.sub(r'\{\{(SITE_TITLE|SITE_DESCRIPTION|SERVER_ADDRESS|LISTING_NAME|SITE_URL|MODE_LABEL|PLUS_HIDDEN|VANILLA_HIDDEN|LISTING_HIDDEN)\}\}', lambda m: html.escape(values[m[1]], quote=True), template)
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
                return self.reply(200, {**self.manager.config.view(), 'panel':self.manager.panel.view(), 'panel_revision':self.manager.panel.revision()})
            except ValueError as e:
                return self.reply(400, {'error':str(e)})
        if self.path.startswith('/api/world-export/'):
            name = self.path.removeprefix('/api/world-export/')
            if not re.fullmatch(r'world-[0-9-]+-[a-f0-9]{8}\.zip', name):
                return self.reply(400, {'error':'Неверное имя экспорта'})
            path = self.manager.base/'exports'/name
            if not path.is_file():
                return self.reply(404, {'error':'Экспорт не найден'})
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Length', str(path.stat().st_size))
            self.send_header('Content-Disposition', f'attachment; filename="{name}"')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Robots-Tag', 'noindex, nofollow')
            self.end_headers()
            with path.open('rb') as source:shutil.copyfileobj(source,self.wfile)
            return
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

    def upload_world(self):
        session = self.session()
        if not self.manager.panel.configured or not session or self.headers.get('X-Hearth') != '1' or not hmac.compare_digest(self.headers.get('X-CSRF-Token',''), session['csrf']):
            self.close_connection = True
            return self.reply(403, {'error':'Войдите в панель и повторите загрузку'})
        if self.headers.get('Content-Type') != 'application/zip':
            self.close_connection = True
            return self.reply(400, {'error':'Ожидается ZIP-архив экспорта Hearth'})
        if self.manager.closing or not self.manager.lock.acquire(blocking=False):
            self.close_connection = True
            return self.reply(409, {'error':'Дождитесь завершения другой операции'})
        try:
            self.connection.settimeout(120)
            result = world_transfer.stage_import(self.manager, self.rfile, int(self.headers.get('Content-Length','0')))
            return self.reply(200,result)
        except (ValueError, OSError) as e:
            self.close_connection = True
            return self.reply(400, {'error':str(e)})
        finally:
            self.manager.lock.release()
            self.connection.settimeout(15)

    def do_POST(self):
        if self.path == '/api/world-import':
            return self.upload_world()
        # Non-simple header forces a same-origin request; no CORS is enabled.
        if self.headers.get('X-Hearth') != '1' or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply(403, {'error': 'Недопустимый запрос'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            limit = 262144 if self.path in ('/api/action', '/api/setup') else 4096
            if not 0 < length <= limit:
                raise ValueError('Недопустимый размер запроса')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Ожидается объект JSON')
            if self.path == '/api/setup':
                if self.manager.panel.configured:
                    return self.reply(409, {'error':'Первичная настройка уже завершена'})
                if not hmac.compare_digest(self.headers.get('X-Setup-Token', ''), self.manager.setup_token or ''):
                    return self.reply(403, {'error':'Обновите страницу мастера и повторите попытку'})
                self.manager.complete_setup(data)
                self.manager.submit(self.manager.boot_action())
                next_url = self.manager.config.load()['landing']['site_url'] + '/admin' if self.manager.panel.load()['cookie_secure'] else '/admin'
                return self.reply(201, {'next_url':next_url})
            if not self.manager.panel.configured:
                return self.reply(409, {'error':'Сначала завершите первоначальную настройку'})
            if self.path == '/api/login':
                with self.auth_lock:
                    now = time.time()
                    while self.attempts and self.attempts[0] < now - 60:
                        self.attempts.popleft()
                    if len(self.attempts) >= 10:
                        return self.reply(429, {'error': 'Слишком много попыток. Подождите минуту.'})
                    self.attempts.append(now)
                    if not self.manager.panel.verify(data.get('password', '')):
                        return self.reply(401, {'error': 'Неверный пароль'})
                    expired = [k for k, v in self.sessions.items() if v['expires'] < now]
                    for k in expired:
                        del self.sessions[k]
                    if len(self.sessions) >= 100:
                        del self.sessions[next(iter(self.sessions))]
                    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                    self.sessions[token] = {'expires': now + 28800, 'csrf': csrf}
                secure = '; Secure' if self.manager.panel.load()['cookie_secure'] else ''
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
            if self.path == '/api/operations':
                if not self.manager.lock.acquire(blocking=False):
                    raise ValueError('Другая операция уже выполняется')
                try:
                    op=data.get('command')
                    if op=='discord':self.manager.operations.configure_discord(data)
                    elif op=='test':self.manager.operations.notify('server','Проверка уведомлений Hearth.',test=True)
                    elif op=='schedule':self.manager.operations.schedule(data)
                    elif op=='cancel':self.manager.operations.cancel()
                    else:raise ValueError('Неизвестная операция')
                finally:self.manager.lock.release()
                return self.reply(200,self.manager.operations.view())
            if self.path == '/api/players':
                if not self.manager.lock.acquire(blocking=False):
                    raise ValueError('Другая операция уже выполняется')
                try:
                    if self.manager.closing:
                        raise ValueError('Панель останавливается')
                    action=data.get('action')
                    message=self.manager.player_access.perform(action, data.get('steam_id'))
                    self.manager.store.event('players', PLAYER_ACTION_NAMES[action]+': Steam_'+steam_id(data['steam_id']))
                    access=self.manager.player_access.view()
                finally:self.manager.lock.release()
                return self.reply(200, {'access':access, 'message':message})
            if self.path == '/api/action':
                action = data.get('action')
                if action not in {'start', 'stop', 'restart', 'backup', 'install', 'restore', 'rollback', 'configure', 'export_world', 'import_world', 'check_panel'}:
                    raise ValueError('Неизвестная операция')
                self.manager.submit(action, data)
                return self.reply(202, {'accepted': True})
            return self.reply(404, {'error': 'Не найдено'})
        except (ValueError, TypeError) as e:
            return self.reply(400, {'error': str(e)})
        except OSError:
            return self.reply(500, {'error':'Не удалось сохранить данные. Проверьте свободное место и права доступа; повторите настройку.'})


def main():
    game_ports()
    os.umask(0o077)
    manager = Manager()
    Handler.manager = manager
    # Existing deployments that still pass their old environment can migrate once.
    legacy_password = os.getenv('PANEL_PASSWORD', '')
    if not manager.panel.configured and len(legacy_password) >= 16 and 'CHANGE_ME' not in legacy_password:
        settings = manager.config.load()
        if len(settings['server']['password']) >= 5:
            atomic_json(manager.config.path, settings)
            manager.panel.save({'auth':password_hash(legacy_password), 'backup_hours':int(os.getenv('BACKUP_HOURS','6')),
                'backup_keep':int(os.getenv('BACKUP_KEEP','12')), 'cookie_secure':os.getenv('COOKIE_SECURE') == '1'})
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
    if manager.panel.configured:
        manager.submit(manager.boot_action())
    else:
        manager.say('Первый запуск: откройте http://localhost:8080 — настройте сервер в браузере. Игра пока не запускается.')
    httpd.serve_forever()
    httpd.server_close()


if __name__ == '__main__':
    main()
