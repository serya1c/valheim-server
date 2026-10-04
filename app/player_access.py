"""Steam player access via Valheim's native, live-reloaded lists."""
import contextlib
import os
import re
import tempfile
import threading
import time

ID = re.compile(r'(?:Steam_)?([0-9]{17})')
TEMP = re.compile(r'// Hearth temporary kick Steam_([0-9]{17}) until ([0-9]{1,12})')
READ_ERROR = 'Не удалось прочитать списки доступа. Проверьте adminlist.txt и bannedlist.txt.'
WRITE_ERROR = 'Не удалось сохранить список доступа. Проверьте права на каталог saves.'
CHANGED_ERROR = 'Список доступа изменился. Обновите страницу и повторите действие.'
LABELS = {'ban':'Бан игрока', 'unban':'Снятие бана', 'admin':'Выдача игровых прав администратора',
          'unadmin':'Снятие игровых прав администратора', 'kick':'Запрос отключения игрока'}
MESSAGES = {
    'ban':'Бан сохранён. Valheim применит его с небольшой задержкой.',
    'unban':'Бан снят. Valheim применит изменение с небольшой задержкой.',
    'admin':'Права администратора игры выданы. Игроку нужно переподключиться.',
    'unadmin':'Права администратора игры сняты. Игроку нужно переподключиться.',
    'kick':'Запрос на отключение сохранён: временный бан на 30 секунд.'}


def steam_id(value):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise ValueError('Введите SteamID64: 17 цифр или Steam_<SteamID64>')
    match = ID.fullmatch(value.strip())
    if not match:
        raise ValueError('Введите SteamID64: 17 цифр или Steam_<SteamID64>')
    return match[1]


class PlayerAccess:
    def __init__(self, manager):
        self.manager = manager
        self.folder = manager.base / 'saves'
        self.lock = threading.RLock()

    def _read(self, name):
        path = self.folder / name
        try:
            if self.folder.is_symlink() or path.is_symlink():
                raise ValueError(READ_ERROR)
            if not path.exists():
                return path, b'', ''
            with path.open('rb') as f:
                raw = f.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError(READ_ERROR)
            return path, raw, raw.decode('utf-8-sig')
        except (OSError, UnicodeError):
            raise ValueError(READ_ERROR) from None

    def _write(self, path, original, text):
        # Publish contents and a strictly increasing mtime together. SyncedList
        # ignores a changed file if its timestamp has not increased.
        temporary = None
        try:
            if self._read(path.name)[1] != original:
                raise ValueError(CHANGED_ERROR)
            old_time = path.stat().st_mtime if path.exists() else 0
            raw = (b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b'') + text.encode('utf-8')
            with tempfile.NamedTemporaryFile(dir=self.folder, prefix=path.name+'.', suffix='.tmp', delete=False) as f:
                temporary = f.name
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            stamp = max(time.time(), old_time + 1)
            os.utime(temporary, (stamp, stamp))
            if self._read(path.name)[1] != original:
                raise ValueError(CHANGED_ERROR)
            os.replace(temporary, path)
        except OSError:
            raise ValueError(WRITE_ERROR) from None
        finally:
            if temporary:
                with contextlib.suppress(OSError):
                    os.unlink(temporary)

    @staticmethod
    def _entries(text):
        ids, other, temporary = set(), 0, {}
        for line in text.splitlines():
            match = ID.fullmatch(line)
            marker = TEMP.fullmatch(line)
            if match:
                ids.add(match[1])
            elif marker:
                temporary[marker[1]] = max(temporary.get(marker[1], 0), int(marker[2]))
            elif line and not line.startswith('//'):
                other += 1
        return ids, other, temporary

    def view(self):
        with self.lock:
            result = {'admins':[], 'banned':[], 'kicks':[], 'other_admins':0, 'other_bans':0, 'error':None}
            try:
                admins, other_admins, _ = self._entries(self._read('adminlist.txt')[2])
                _, _, text = self._read('bannedlist.txt')
                banned, other_bans, temporary = self._entries(text)
                lines = set(text.splitlines())
                only_temporary = {sid for sid in temporary if 'Steam_'+sid in lines and sid not in lines}
                result.update(admins=sorted(admins), banned=sorted(banned-only_temporary), other_admins=other_admins, other_bans=other_bans,
                              kicks=[{'steam_id':sid, 'until':until} for sid, until in sorted(temporary.items()) if 'Steam_'+sid in lines])
            except ValueError:
                result['error'] = READ_ERROR
            return result

    def perform(self, action, value):
        if not isinstance(action, str) or action not in LABELS:
            raise ValueError('Неизвестное действие с игроком')
        sid = steam_id(value)
        with self.lock:
            path, raw, text = self._read('adminlist.txt' if action in ('admin','unadmin') else 'bannedlist.txt')
            ids, _, temporary = self._entries(text)
            if action == 'kick':
                if not self.manager.running():
                    raise ValueError('Для отключения игрока сервер должен быть запущен')
                if sid in temporary and 'Steam_'+sid in text.splitlines():
                    raise ValueError('Для этого SteamID уже выполняется отключение')
                if sid in ids:
                    raise ValueError('Игрок уже забанен. Постоянный бан не снимается при отключении.')
                addition = f'// Hearth temporary kick Steam_{sid} until {int(time.time())+30}\nSteam_{sid}\n'
                updated = text + ('\n' if text and not text.endswith(('\r','\n')) else '') + addition
            else:
                lines = []
                for line in text.splitlines(keepends=True):
                    entry = line.rstrip('\r\n')
                    marker = TEMP.fullmatch(entry)
                    match = ID.fullmatch(entry)
                    if marker and marker[1] == sid:
                        continue  # A permanent ban replaces the temporary lease.
                    if action in ('unban','unadmin') and match and match[1] == sid:
                        continue
                    lines.append(line)
                updated = ''.join(lines)
                if action in ('ban','admin') and sid not in ids:
                    updated += ('\n' if updated and not updated.endswith(('\r','\n')) else '') + 'Steam_'+sid+'\n'
            if updated != text:
                self._write(path, raw, updated)
            return MESSAGES[action]

    def cleanup(self, force=False):
        with self.lock:
            path, raw, text = self._read('bannedlist.txt')
            _, _, temporary = self._entries(text)
            lines = set(text.splitlines())
            expired = {sid for sid, until in temporary.items() if force or time.time() >= until or 'Steam_'+sid not in lines}
            if not expired:
                return
            kept = []
            for line in text.splitlines(keepends=True):
                entry = line.rstrip('\r\n')
                marker = TEMP.fullmatch(entry)
                if (marker and marker[1] in expired) or (entry.startswith('Steam_') and entry[6:] in expired):
                    continue
                kept.append(line)
            self._write(path, raw, ''.join(kept))
            for sid in sorted(expired):
                self.manager.store.event('players', 'Временный бан снят: Steam_'+sid)
