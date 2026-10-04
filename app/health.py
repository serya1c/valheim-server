"""Cached, private diagnostics scoped to the game process and its container."""
import copy
from contextlib import closing
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time

from configuration import atomic_text, world_name
from world_transfer import MAX_FILES, chunk_file, validate_chunk_set

FRESH_SECONDS = 30
STARTUP_SECONDS = 180


def process_sample(proc_root, pid):
    """Read process ticks and RSS without summing host CPU or host memory."""
    path = Path(proc_root) / str(pid)
    fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
    ticks = int(fields[11]) + int(fields[12])
    identity = (int(pid), int(fields[19]))
    match = re.search(r'^VmRSS:\s*(\d+)\s+kB\s*$', (path / 'status').read_text(), re.M)
    return identity, ticks, int(match[1]) * 1024 if match else None


def container_memory(proc_root):
    """Resolve the current cgroup through mountinfo, including namespace roots."""
    memberships = []
    for line in (Path(proc_root) / 'self/cgroup').read_text().splitlines():
        _, controllers, path = line.split(':', 2)
        memberships.append((controllers.split(',') if controllers else [], path))
    for line in (Path(proc_root) / 'self/mountinfo').read_text().splitlines():
        left, right = line.split(' - ', 1)
        fields, info = left.split(), right.split()
        kind = info[0]
        if kind not in ('cgroup2', 'cgroup'):
            continue
        root = Path(fields[3].replace('\\040', ' '))
        mount = Path(fields[4].replace('\\040', ' '))
        for controllers, path in memberships:
            if kind == 'cgroup2' and controllers or kind == 'cgroup' and ('memory' not in controllers or 'memory' not in info[2].split(',')):
                continue
            if path == '/':
                directory = mount
            else:
                try:
                    directory = mount / Path(path).relative_to(root)
                except ValueError:
                    continue
            usage = int((directory / ('memory.current' if kind == 'cgroup2' else 'memory.usage_in_bytes')).read_text().strip())
            value = (directory / ('memory.max' if kind == 'cgroup2' else 'memory.limit_in_bytes')).read_text().strip()
            limit = None if value == 'max' else int(value)
            if limit is not None and (limit <= 0 or limit >= 1 << 60):
                limit = None
            return {'memory_bytes': max(0, usage), 'memory_limit_bytes': limit}
    return {'memory_bytes': None, 'memory_limit_bytes': None}


def selected_world(base, name):
    """Inspect only the selected world; exclude other worlds and automatic copies."""
    result = {'name': name, 'last_save_at': None, 'format': None, 'error': None}
    try:
        name = world_name(name)
        folder = Path(base) / 'saves/worlds_local'
        directory = folder / name
        if folder.is_symlink() or directory.is_symlink():
            raise ValueError()
        if directory.exists():
            if not directory.is_dir():
                raise ValueError()
            files = []
            with os.scandir(directory) as entries:
                for entry in entries:
                    if len(files) >= MAX_FILES or not chunk_file(entry.name) or not entry.is_file(follow_symlinks=False):
                        raise ValueError()
                    info = entry.stat(follow_symlinks=False)
                    if not info.st_size:
                        raise ValueError()
                    files.append((entry.name, info.st_mtime))
            validate_chunk_set(name for name, _ in files)
            result.update(format='directory', last_save_at=max(at for _, at in files))
        else:
            files = [folder / (name + suffix) for suffix in ('.db', '.fwl')]
            if not any(path.exists() for path in files):
                return result
            if any(path.is_symlink() or not path.is_file() or not path.stat().st_size for path in files):
                raise ValueError()
            result.update(format='classic', last_save_at=max(path.stat().st_mtime for path in files))
    except (OSError, ValueError):
        result['error'] = 'Не удалось определить запись выбранного мира'
    return result


class HealthMonitor:
    def __init__(self, manager, proc_root='/proc', interval=10, container=None):
        self.manager = manager
        self.proc_root = Path(proc_root)
        self.interval = interval
        self.container = (Path('/.dockerenv').exists() or Path('/run/.containerenv').exists()) if container is None else container
        self.lock = threading.RLock()
        self.worker = None
        self.last_scheduled = None
        self.last_cpu = None
        self.last_response_at = None
        self.observed_start = None
        self.sampled_start = None
        self.backup_marker = Path(manager.base) / 'health-last-backup.json'
        self.backup_info = None
        self.last_backup_check = None
        self.data = {
            'sampled_at': None,
            'process': {'running': False, 'cpu_percent': None, 'rss_bytes': None},
            'container': {'memory_bytes': None, 'memory_limit_bytes': None},
            'disk': {'free_bytes': None, 'total_bytes': None},
            'world': {'name': None, 'last_save_at': None, 'format': None, 'error': None},
            'backup': {'last_success_at': None, 'name': None},
        }

    def tick(self):
        """Never scan files or wait for a sampler from the watch/status thread."""
        now = time.monotonic()
        with self.lock:
            self._capture_response(time.time())
            if self.worker and self.worker.is_alive() or self.last_scheduled is not None and now - self.last_scheduled < self.interval:
                return
            self.last_scheduled = now
            self.worker = threading.Thread(target=self.sample, daemon=True, name='hearth-health')
            self.worker.start()

    def _capture_response(self, now):
        running = bool(self.manager.running())
        if running and self.observed_start != self.manager.started:
            self.observed_start = self.manager.started
            self.last_response_at = None
        online = self.manager.online
        if running and isinstance(online, dict):
            at = online.get('at')
            if type(at) in (int, float) and math.isfinite(at) and self.manager.started <= at <= now + 1:
                self.last_response_at = max(self.last_response_at or 0, at)
        return running

    def _backup_stat(self, name):
        if not isinstance(name, str) or not re.fullmatch(r'[0-9]{8}-[0-9]{6}-[a-f0-9]{6}-[A-Za-z0-9_-]+\.tar\.gz', name):
            return None
        folder = Path(self.manager.base) / 'backups'
        path = folder / name
        if folder.is_symlink() or path.is_symlink() or not path.is_file():
            return None
        info = path.stat()
        return info if info.st_size else None

    def record_backup(self, name, at=None):
        """Call only after Manager.backup has completed its atomic rename."""
        try:
            info = self._backup_stat(name)
            if info is None:
                return False
            at = time.time() if at is None else at
            if type(at) not in (int, float) or not math.isfinite(at) or at <= 0:
                return False
            marker = {'name': name, 'completed_at': at, 'size': info.st_size, 'mtime_ns': info.st_mtime_ns}
            with self.lock:
                self.backup_info = marker
                self.data['backup'] = {'last_success_at': marker['completed_at'], 'name': name}
                try:
                    atomic_text(self.backup_marker, json.dumps(marker))
                except OSError:
                    pass  # A completed game backup must not fail due to health metadata.
            return True
        except OSError:
            return False

    def _last_backup(self):
        now = time.monotonic()
        with self.lock:
            if self.last_backup_check is not None and now - self.last_backup_check < 30:
                return dict(self.data['backup'])
            self.last_backup_check = now
            marker = self.backup_info
        if marker is None:
            try:
                marker = json.loads(self.backup_marker.read_text())
            except (OSError, ValueError):
                pass
        rejected_name = None
        try:
            info = self._backup_stat(marker.get('name')) if isinstance(marker, dict) else None
            at = marker.get('completed_at') if isinstance(marker, dict) else None
            if info and marker.get('size') == info.st_size and marker.get('mtime_ns') == info.st_mtime_ns and type(at) in (int, float) and math.isfinite(at):
                return {'last_success_at': at, 'name': marker['name']}
            if isinstance(marker, dict):
                rejected_name = marker.get('name')
        except (OSError, ValueError):
            pass
        # Older versions recorded success after the final rename in Store.events.
        database = Path(self.manager.base) / 'panel.sqlite'
        if database.is_file():
            try:
                with closing(sqlite3.connect(str(database), timeout=.1)) as connection:
                    events = connection.execute("SELECT ts,message FROM events WHERE kind='backup' ORDER BY ts DESC LIMIT 256").fetchall()
                for at, name in events:
                    if name != rejected_name and type(at) in (int, float) and math.isfinite(at) and self._backup_stat(name):
                        return {'last_success_at': at, 'name': name}
            except (OSError, sqlite3.Error, ValueError):
                pass
        return {'last_success_at': None, 'name': None}

    def sample(self):
        started = self.manager.started
        with self.lock:
            backup_at_start = self.backup_info
            self._capture_response(time.time())
        result = {
            'sampled_at': time.time(),
            'process': {'running': self.manager.running(), 'cpu_percent': None, 'rss_bytes': None},
            'container': {'memory_bytes': None, 'memory_limit_bytes': None},
            'disk': {'free_bytes': None, 'total_bytes': None},
            'world': {'name': None, 'last_save_at': None, 'format': None, 'error': None},
            'backup': self._last_backup(),
        }
        if result['process']['running']:
            try:
                identity, ticks, rss = process_sample(self.proc_root, self.manager.proc.pid)
                now = time.monotonic()
                clock = os.sysconf('SC_CLK_TCK')
                if self.last_cpu and self.last_cpu[0] == identity:
                    elapsed = now - self.last_cpu[2]
                    if elapsed > 0 and ticks >= self.last_cpu[1]:
                        result['process']['cpu_percent'] = (ticks - self.last_cpu[1]) / clock / elapsed * 100
                self.last_cpu = identity, ticks, now
                result['process']['rss_bytes'] = rss
            except (OSError, ValueError, IndexError, AttributeError, TypeError):
                self.last_cpu = None
        else:
            self.last_cpu = None
        if self.container:
            try:
                result['container'] = container_memory(self.proc_root)
            except (OSError, ValueError, IndexError):
                pass
        try:
            usage = shutil.disk_usage(self.manager.base)
            result['disk'] = {'free_bytes': usage.free, 'total_bytes': usage.total}
        except OSError:
            pass
        try:
            result['world'] = selected_world(self.manager.base, self.manager.config.load()['world_name'])
        except (OSError, ValueError, KeyError, TypeError):
            result['world']['error'] = 'Не удалось определить запись выбранного мира'
        with self.lock:
            # A backup can complete while the worker is scanning the world.
            if self.backup_info is not backup_at_start and self.backup_info and (result['backup']['last_success_at'] or 0) < self.backup_info['completed_at']:
                result['backup'] = dict(self.data['backup'])
            self.data = result
            self.sampled_start = started

    def view(self):
        now = time.time()
        with self.lock:
            result = copy.deepcopy(self.data)
            running = self._capture_response(now)
            response = self.last_response_at
        age = max(0, now - response) if response is not None else None
        result['process']['running'] = running
        if not running or self.sampled_start != self.manager.started:
            result['process'].update(cpu_percent=None, rss_bytes=None)
        result['a2s'] = {'fresh': running and age is not None and age <= FRESH_SECONDS, 'last_response_at': response, 'age_seconds': age}
        result['diagnostics'] = self.diagnostics(result, now)
        return result

    def diagnostics(self, data, now):
        result = []
        def add(code, level, title, detail, action, link):
            result.append({'code': code, 'level': level, 'title': title, 'detail': detail, 'action': action, 'link': link})
        if not data['process']['running']:
            add('stopped', 'info', 'Игровой процесс остановлен', 'Веб-панель доступна независимо от игры.', 'Запустите сервер в обзоре, если хотите принимать игроков.', '#overview')
        elif not data['a2s']['fresh']:
            if now - self.manager.started <= STARTUP_SECONDS and data['a2s']['last_response_at'] is None:
                add('startup', 'info', 'Ожидаем первый ответ A2S', 'Игровой процесс запущен. Загрузка мира может занять до 180 секунд.', 'Следите за журналом запуска. Ответ A2S не подтверждает вход игрового клиента.', '#journal')
            else:
                add('a2s_timeout', 'warning', 'Нет свежего ответа A2S', 'Процесс игры работает, но статистика онлайна неизвестна. Это не подтверждает остановку игры.', 'Проверьте журнал и параметры игрового порта. Неизвестный онлайн задерживает обслуживание.', '#journal')
        disk = data['disk']
        if disk['free_bytes'] is not None and disk['total_bytes'] and (disk['free_bytes'] < 1024 ** 3 or disk['free_bytes'] / disk['total_bytes'] < .05):
            add('disk_low', 'warning', 'Мало места в каталоге данных', 'Свободно менее 1 ГиБ или менее 5% файловой системы данных. Копии и обновления требуют дополнительного места.', 'Скачайте важные копии на другой диск и освободите место перед обновлением.', '#world')
        container = data['container']
        if container['memory_bytes'] is not None and container['memory_limit_bytes'] and container['memory_bytes'] / container['memory_limit_bytes'] >= .9:
            add('memory_limit', 'warning', 'Память контейнера близка к лимиту', 'Использовано не менее 90% доступного лимита cgroup. В него входят игра и панель.', 'Проверьте нагрузку модов и лимит памяти контейнера на хосте.', '#settings')
        if data['world']['error']:
            add('world_unavailable', 'warning', 'Не удалось определить запись выбранного мира', 'Файлы выбранного мира отсутствуют, недоступны или имеют незавершённый формат.', 'Проверьте имя мира и журнал. После первого сохранения данные появятся автоматически.', '#world')
        if data['backup']['last_success_at'] is None:
            add('backup_missing', 'info', 'Нет записи об успешной резервной копии', 'Временные и сторонние архивы не считаются завершёнными копиями панели.', 'Создайте резервную копию и скачайте её на другое устройство.', '#world')
        return result
