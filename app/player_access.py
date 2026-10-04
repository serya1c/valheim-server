"""Steam player access via Valheim's native, live-reloaded lists."""
import contextlib
import copy
import json
import math
import os
import re
import tempfile
import threading
import time
import unicodedata

ID = re.compile(r'(?:Steam_)?([0-9]{17})')
TEMP = re.compile(r'// Hearth temporary kick Steam_([0-9]{17}) until ([0-9]{1,12})')
TIMED = re.compile(r'// Hearth timed ban Steam_([0-9]{17}) until ([0-9]{1,12})')
MAX_DURATION = 365 * 86400
META_ERROR = 'Не удалось прочитать журнал модерации. Проверьте moderation.json.'
META_WRITE_ERROR = 'Не удалось сохранить журнал модерации. Проверьте права и свободное место.'
READ_ERROR = 'Не удалось прочитать списки доступа. Проверьте adminlist.txt и bannedlist.txt.'
WRITE_ERROR = 'Не удалось сохранить список доступа. Проверьте права на каталог saves.'
CHANGED_ERROR = 'Список доступа изменился. Обновите страницу и повторите действие.'
LABELS = {'ban':'Бан игрока', 'unban':'Снятие бана', 'admin':'Выдача игровых прав администратора',
          'unadmin':'Снятие игровых прав администратора', 'kick':'Запрос отключения игрока', 'profile':'Сохранение заметки об игроке'}
MESSAGES = {
    'ban':'Бан сохранён. Valheim применит его с небольшой задержкой.',
    'unban':'Бан снят. Valheim применит изменение с небольшой задержкой.',
    'admin':'Права администратора игры выданы. Игроку нужно переподключиться.',
    'unadmin':'Права администратора игры сняты. Игроку нужно переподключиться.',
    'kick':'Запрос на отключение сохранён: временный бан на 30 секунд.',
    'profile':'Имя и заметка игрока сохранены. Они доступны только администраторам панели.'}


def steam_id(value):
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Введите SteamID64: 17 цифр или Steam_<SteamID64>')
    match = ID.fullmatch(value.strip(' '))
    if not match:
        raise ValueError('Введите SteamID64: 17 цифр или Steam_<SteamID64>')
    return match[1]


def bounded_text(value, label, maximum, multiline=False):
    if not isinstance(value, str) or len(value) > maximum or any(
            (unicodedata.category(c) == 'Cc' and not (multiline and c in '\n\r\t')) or (not multiline and c in '\u2028\u2029') for c in value):
        raise ValueError(f'{label}: текст до {maximum} символов без управляющих знаков')
    return value.strip()


def ban_until(duration_hours, until):
    if duration_hours is None and until is None:
        return None
    if duration_hours is not None and until is not None:
        raise ValueError('Укажите длительность или время окончания бана')
    value = duration_hours if duration_hours is not None else until
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Срок бана: число от одной минуты до 365 дней')
    now = time.time()
    seconds = value * 3600 if duration_hours is not None else value - now
    if not 60 <= seconds <= MAX_DURATION:
        raise ValueError('Срок бана: число от одной минуты до 365 дней')
    return math.ceil(now + seconds)


class PlayerAccess:
    def __init__(self, manager):
        self.manager = manager
        self.folder = manager.base / 'saves'
        self.path = manager.base / 'moderation.json'
        self.lock = threading.RLock()

    def _metadata(self):
        empty = {'profiles':{}, 'bans':{}, 'history':[]}
        try:
            if self.path.is_symlink():
                raise ValueError(META_ERROR)
            if not self.path.exists():
                return b'', empty
            with self.path.open('rb') as file:
                raw = file.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError(META_ERROR)
            data = json.loads(raw)
            if not isinstance(data, dict) or set(data) != set(empty):
                raise ValueError(META_ERROR)
            if not isinstance(data['profiles'], dict) or len(data['profiles']) > 200 or not isinstance(data['bans'], dict) or len(data['bans']) > 1000 or not isinstance(data['history'], list) or len(data['history']) > 200:
                raise ValueError(META_ERROR)
            for sid, profile in data['profiles'].items():
                if steam_id(sid) != sid or not isinstance(profile, dict) or set(profile) != {'alias','notes'}:
                    raise ValueError(META_ERROR)
                bounded_text(profile['alias'], 'Имя игрока', 80)
                bounded_text(profile['notes'], 'Заметка', 2000, True)
            for sid, detail in data['bans'].items():
                if steam_id(sid) != sid or not isinstance(detail, dict) or set(detail) != {'reason','until'}:
                    raise ValueError(META_ERROR)
                bounded_text(detail['reason'], 'Причина бана', 300)
                if detail['until'] is not None and (type(detail['until']) is not int or not 0 <= detail['until'] <= 999999999999):
                    raise ValueError(META_ERROR)
            for item in data['history']:
                if not isinstance(item, dict) or set(item) != {'steam_id','action','at','reason','until'} or steam_id(item['steam_id']) != item['steam_id'] or item['action'] not in {*LABELS, 'expiry'}:
                    raise ValueError(META_ERROR)
                bounded_text(item['reason'], 'Причина бана', 300)
                if type(item['at']) not in (int,float) or not math.isfinite(item['at']) or not 0 <= item['at'] <= 999999999999:
                    raise ValueError(META_ERROR)
                if item['until'] is not None and (type(item['until']) is not int or not 0 <= item['until'] <= 999999999999):
                    raise ValueError(META_ERROR)
            return raw, data
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            raise ValueError(META_ERROR) from None

    def _save_metadata(self, original, data):
        temporary = None
        try:
            raw = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            if len(raw) > 1024 * 1024:
                raise ValueError(META_WRITE_ERROR)
            with tempfile.NamedTemporaryFile(dir=self.manager.base, prefix='moderation.', suffix='.tmp', delete=False) as file:
                temporary = file.name
                file.write(raw)
                file.flush()
                os.fsync(file.fileno())
            if self._metadata()[0] != original:
                raise ValueError('Журнал модерации изменился. Обновите страницу и повторите действие.')
            os.replace(temporary, self.path)
        except OSError:
            raise ValueError(META_WRITE_ERROR) from None
        finally:
            if temporary:
                with contextlib.suppress(OSError):
                    os.unlink(temporary)

    def _commit(self, path, original, previous, updated, metadata_raw, metadata):
        changed = updated != previous
        if changed:
            self._write(path, original, updated)
        try:
            self._save_metadata(metadata_raw, metadata)
        except ValueError:
            # A metadata failure cannot leave an unaudited action in the native list.
            # Compare again before reverting so a concurrent game edit stays intact.
            if changed:
                written = (b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b'') + updated.encode('utf-8')
                with contextlib.suppress(ValueError):
                    self._write(path, written, previous)
            raise

    @staticmethod
    def _record(data, sid, action, reason='', until=None):
        data['history'].append({'steam_id':sid, 'action':action, 'at':time.time(), 'reason':reason, 'until':until})
        data['history'] = data['history'][-200:]

    def _notify(self, sid, action, reason='', until=None):
        operations = getattr(self.manager, 'operations', None)
        if not operations:
            return
        text = {'ban':'Бан сохранён', 'unban':'Бан снят', 'expiry':'Срок временного бана истёк'}[action] + ': Steam_' + sid
        if until is not None:
            text += '. Окончание: ' + time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(until))
        if reason:
            text += '. Причина: ' + reason.replace('@', '@\u200b')
        with contextlib.suppress(Exception):
            operations.notify('moderation', text)

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
            marker = TEMP.fullmatch(line) or TIMED.fullmatch(line)
            if match:
                ids.add(match[1])
            elif marker:
                temporary[marker[1]] = max(temporary.get(marker[1], 0), int(marker[2]))
            elif line and not line.startswith('//'):
                other += 1
        return ids, other, temporary

    @staticmethod
    def _leases(text):
        result = {}
        for line in text.splitlines():
            for kind, pattern in [('kick', TEMP), ('ban', TIMED)]:
                marker = pattern.fullmatch(line)
                if marker:
                    result[(kind, marker[1])] = max(result.get((kind, marker[1]), 0), int(marker[2]))
        return result

    def view(self):
        with self.lock:
            result = {'admins':[], 'banned':[], 'kicks':[], 'timed_bans':[], 'profiles':{}, 'history':[], 'ban_details':{}, 'other_admins':0, 'other_bans':0, 'error':None}
            try:
                admins, other_admins, _ = self._entries(self._read('adminlist.txt')[2])
                _, _, text = self._read('bannedlist.txt')
                _, data = self._metadata()
                banned, other_bans, _ = self._entries(text)
                temporary = self._leases(text)
                lines = set(text.splitlines())
                only_temporary = {sid for _, sid in temporary if 'Steam_'+sid in lines and sid not in lines and text.splitlines().count('Steam_'+sid) == 1}
                result.update(admins=sorted(admins), banned=sorted(banned-only_temporary), other_admins=other_admins, other_bans=other_bans,
                              kicks=[{'steam_id':sid, 'until':until} for (kind, sid), until in sorted(temporary.items()) if kind == 'kick' and 'Steam_'+sid in lines],
                              timed_bans=[{'steam_id':sid, 'until':until, 'reason':data['bans'].get(sid, {}).get('reason','') if data['bans'].get(sid, {}).get('until') == until else ''} for (kind, sid), until in sorted(temporary.items()) if kind == 'ban' and 'Steam_'+sid in lines],
                              profiles=copy.deepcopy(data['profiles']), history=list(reversed(copy.deepcopy(data['history']))),
                              ban_details={sid:copy.deepcopy(data['bans'][sid]) for sid in banned if sid in data['bans']})
            except ValueError as error:
                result['error'] = str(error)
            return result

    def act(self, action, value, **kwargs):
        return self.perform(action, value, **kwargs)

    def perform(self, action, value, *, reason='', duration_hours=None, until=None, alias=None, notes=None):
        if not isinstance(action, str) or action not in LABELS:
            raise ValueError('Неизвестное действие с игроком')
        sid = steam_id(value)
        reason = bounded_text(reason, 'Причина бана', 300)
        if action != 'ban' and (duration_hours is not None or until is not None):
            raise ValueError('Срок можно задать только для бана')
        expires = ban_until(duration_hours, until) if action == 'ban' else None
        if action != 'profile' and (alias is not None or notes is not None):
            raise ValueError('Имя и заметку сохраняйте отдельно от действия')
        if action == 'profile':
            alias = bounded_text(alias if alias is not None else '', 'Имя игрока', 80)
            notes = bounded_text(notes if notes is not None else '', 'Заметка', 2000, True)
        with self.lock:
            metadata_raw, data = self._metadata()
            if action == 'profile':
                if (alias or notes) and sid not in data['profiles'] and len(data['profiles']) >= 200:
                    raise ValueError('Сохранено слишком много заметок об игроках. Удалите ненужную заметку.')
                if alias or notes:
                    data['profiles'][sid] = {'alias':alias, 'notes':notes}
                else:
                    data['profiles'].pop(sid, None)
                self._record(data, sid, action)
                self._save_metadata(metadata_raw, data)
                return MESSAGES[action]
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
            elif action == 'ban' and expires is not None:
                native = 'Steam_'+sid
                if sid in ids and (sid not in temporary or sid in text.splitlines() or text.splitlines().count(native) > 1):
                    raise ValueError('Постоянный бан уже установлен. Сначала снимите его, чтобы задать срок.')
                kept = []
                for line in text.splitlines(keepends=True):
                    marker = TEMP.fullmatch(line.rstrip('\r\n')) or TIMED.fullmatch(line.rstrip('\r\n'))
                    if not marker or marker[1] != sid:
                        kept.append(line)
                updated = ''.join(kept)
                updated += ('\n' if updated and not updated.endswith(('\r','\n')) else '') + f'// Hearth timed ban Steam_{sid} until {expires}\n'
                if sid not in ids:
                    updated += native+'\n'
            else:
                lines = []
                for line in text.splitlines(keepends=True):
                    entry = line.rstrip('\r\n')
                    marker = TEMP.fullmatch(entry) or TIMED.fullmatch(entry)
                    match = ID.fullmatch(entry)
                    if action in ('ban','unban') and marker and marker[1] == sid:
                        continue  # A permanent ban replaces the temporary lease.
                    if action in ('unban','unadmin') and match and match[1] == sid:
                        continue
                    lines.append(line)
                updated = ''.join(lines)
                if action in ('ban','admin') and sid not in ids:
                    updated += ('\n' if updated and not updated.endswith(('\r','\n')) else '') + 'Steam_'+sid+'\n'
            if action == 'ban':
                if sid not in data['bans'] and len(data['bans']) >= 1000:
                    raise ValueError('В журнале слишком много блокировок. Снимите ненужные блокировки.')
                data['bans'][sid] = {'reason':reason, 'until':expires}
            elif action == 'unban':
                reason = reason or data['bans'].get(sid, {}).get('reason','')
                data['bans'].pop(sid, None)
            self._record(data, sid, action, reason, expires)
            self._commit(path, raw, text, updated, metadata_raw, data)
            if action in ('ban','unban'):
                self._notify(sid, action, reason, expires)
            if expires is not None:
                return 'Временный бан сохранён. Он будет снят автоматически после окончания срока.'
            return MESSAGES[action]

    def cleanup(self, force=False):
        with self.lock:
            path, raw, text = self._read('bannedlist.txt')
            temporary = self._leases(text)
            lines = set(text.splitlines())
            expired = {key for key, until in temporary.items() if (force and key[0] == 'kick') or time.time() >= until or 'Steam_'+key[1] not in lines}
            if not expired:
                return
            metadata_raw, data = self._metadata()
            removed_ids = {sid for _, sid in expired if not any(key[1] == sid and key not in expired for key in temporary)}
            kept = []
            removed_entries = set()
            for line in text.splitlines(keepends=True):
                entry = line.rstrip('\r\n')
                kick = TEMP.fullmatch(entry)
                timed = TIMED.fullmatch(entry)
                if (kick and ('kick', kick[1]) in expired) or (timed and ('ban', timed[1]) in expired):
                    continue
                if entry.startswith('Steam_') and entry[6:] in removed_ids and entry[6:] not in removed_entries:
                    removed_entries.add(entry[6:])
                    continue
                kept.append(line)
            notifications = []
            for kind, sid in sorted(expired):
                if kind == 'ban':
                    detail = data['bans'].pop(sid, {})
                    reason = detail.get('reason','') if detail.get('until') == temporary[(kind,sid)] else ''
                    self._record(data, sid, 'expiry', reason, temporary[(kind,sid)])
                    notifications.append((sid, reason))
            self._commit(path, raw, text, ''.join(kept), metadata_raw, data)
            for sid in sorted(removed_ids):
                self.manager.store.event('players', 'Временный бан снят: Steam_'+sid)
            for sid, reason in notifications:
                self._notify(sid, 'expiry', reason)
