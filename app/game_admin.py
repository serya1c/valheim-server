"""Private, expiring command spool for the bundled in-game admin plugin.

No game socket, shell, RCON, or HTTP listener is exposed by the plugin. Requests
cross the container's private filesystem and run on the game's Unity thread.
"""
import json
import math
import os
from pathlib import Path
import re
import secrets
import time
import xml.etree.ElementTree as ET

BUILTIN_ID = 'Hearth-ValheimAdmin'
BUNDLE = Path(__file__).parent / 'builtin-mods' / 'ValheimAdminRu.zip'
METADATA = BUNDLE.with_suffix('.json')
HEX = re.compile(r'[a-f0-9]{32}\Z')
STEAM = re.compile(r'7656119\d{10}\Z')
ACTIONS = frozenset(('TeleportMap', 'TeleportToPlayer', 'SummonPlayer', 'GodSelf', 'GodPlayer',
    'SpawnItem', 'SpawnMob', 'Flatten', 'HammerToggle', 'HammerStrike', 'RaiseTerrain',
    'LowerTerrain', 'FlySelf', 'UndoTerrain', 'CleanupSpawn', 'ReturnTeleport', 'TeleportSaved',
    'HealPlayer', 'RestoreStaminaPlayer', 'ClearEffectsPlayer', 'BuildToggle', 'RepairArea', 'SetRole'))
TARGET_ACTIONS = frozenset(('TeleportToPlayer', 'SummonPlayer', 'GodPlayer', 'HealPlayer',
                           'RestoreStaminaPlayer', 'ClearEffectsPlayer', 'SetRole'))
MAX_XML = 4 * 1024 * 1024


def builtin_info():
    try:
        value = json.loads(METADATA.read_text(encoding='utf-8'))
        if (value['id'] != BUILTIN_ID or not re.fullmatch(r'[a-f0-9]{64}', value['sha256'])
                or not isinstance(value['games'], list) or not BUNDLE.is_file()):
            raise ValueError()
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _xml(path):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_XML:
        raise ValueError('Недопустимый файл игрового моста')
    raw = path.read_bytes()
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Недопустимый XML игрового моста')
    try:
        return ET.fromstring(raw)
    except ET.ParseError as error:
        raise ValueError('Повреждён снимок игрового моста') from error


def _atomic(path, element):
    temporary = path.with_suffix('.' + secrets.token_hex(8) + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(ET.tostring(element, encoding='utf-8', xml_declaration=True))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class GameAdmin:
    def __init__(self, manager):
        self.manager = manager
        self.root = manager.base / 'admin-bridge'
        if self.root.is_symlink():
            raise ValueError('Каталог игрового моста не должен быть ссылкой')
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.requests = {}

    def installed(self):
        return next((p for p in self.manager.mods.view()['packages'] if p['id'] == BUILTIN_ID
                     and p['enabled'] and p['scope'] == 'both'), None)

    def prepare_start(self):
        # Queued commands must never be replayed on another world/process.
        self.requests.clear()
        for path in self.root.iterdir():
            if path.name == 'status.xml' or re.fullmatch(r'(?:command|result)-[a-f0-9]{32}\.xml', path.name):
                path.unlink(missing_ok=True)

    def _status(self):
        root = _xml(self.root / 'status.xml')
        if (root.tag != 'status' or root.get('protocol') != '1'
                or not HEX.fullmatch(root.get('session', ''))):
            raise ValueError('Несовместимый игровой мост')
        stamp = float(root.get('at', '0'))
        if not math.isfinite(stamp) or not -5 <= time.time() - stamp <= 15:
            raise ValueError('Игровой мост давно не отвечает')
        return root

    def view(self):
        installed = self.installed()
        value = {'available': False, 'installed': bool(installed), 'players': [], 'items': [],
                 'mobs': [], 'audit': [], 'session': None, 'message': ''}
        if (self.manager.metadata() or {}).get('mode') not in ('plus', 'modded'):
            value['message'] = 'Игровые инструменты доступны в режиме Valheim Plus или BepInEx'
            return value
        if not installed:
            value['message'] = 'Установите и включите Hearth Admin в разделе «Моды»'
            return value
        if self.manager.busy or self.manager.closing or not self.manager.running():
            value['message'] = 'Дождитесь запуска сервера и завершения обслуживания'
            return value
        try:
            root = self._status()
            if root.get('mod') != installed['version']:
                raise ValueError('Версия игрового моста отличается от установленного пакета')
            value.update(available=True, session=root.get('session'), mod=root.get('mod'),
                         game=root.get('game'), world=root.get('world'), at=float(root.get('at')))
            for row in root.findall('./players/player')[:300]:
                steam = row.get('steam_id', '')
                if not STEAM.fullmatch(steam):
                    continue
                coordinates = {k: float(row.get(k, '0')) for k in ('x', 'y', 'z')}
                if not all(math.isfinite(number) for number in coordinates.values()):
                    raise ValueError('Повреждён снимок игрового моста')
                value['players'].append({**{k: row.get(k, '')[:300] for k in ('name', 'identity', 'role')},
                    'steam_id': steam, **{k: row.get(k) == 'true' for k in ('ready', 'alive', 'god', 'flying', 'building', 'hammer', 'can_return', 'points_ready')},
                    **coordinates,
                    'points': [{k: p.get(k, '') for k in ('id', 'name', 'x', 'y', 'z')}
                               for p in row.findall('./points/point')[:100]]})
            for kind in ('items', 'mobs'):
                for row in root.findall('./' + kind + '/entry')[:5000]:
                    prefab = row.get('prefab', '')
                    if prefab and len(prefab) <= 160:
                        value[kind].append({'prefab': prefab, 'name': row.get('name', prefab)[:300],
                                            'name_en': row.get('name_en', row.get('name', prefab))[:300]})
            value['audit'] = [{k: row.get(k, '')[:2000] for k in ('utc', 'actor', 'action', 'details', 'result', 'details_en', 'result_en')}
                              for row in root.findall('./audit/row')[-300:]]
        except (OSError, ValueError) as error:
            value.update(available=False, session=None, players=[], items=[], mobs=[], audit=[])
            value['message'] = str(error) if isinstance(error, ValueError) else 'Игровой мост ещё не готов. Проверьте загрузку Hearth Admin в журнале.'
        return value

    @staticmethod
    def validate(data):
        if not isinstance(data, dict) or set(data) - {'session', 'action', 'actor_steam', 'target_steam',
                'prefab', 'count', 'radius', 'height', 'enabled', 'x', 'y', 'z', 'role', 'text', 'hammer_targets', 'point_id'}:
            raise ValueError('Неизвестные параметры игровой команды')
        action = data.get('action')
        if action not in ACTIONS or not HEX.fullmatch(str(data.get('session', ''))):
            raise ValueError('Недопустимая игровая команда или сессия')
        actor = data.get('actor_steam')
        if not isinstance(actor, str) or not STEAM.fullmatch(actor):
            raise ValueError('Выберите исполнителя по SteamID')
        values = {'action': action, 'session': data['session'], 'actor_steam': actor}
        if action in TARGET_ACTIONS:
            target = data.get('target_steam')
            if not isinstance(target, str) or not STEAM.fullmatch(target):
                raise ValueError('Выберите целевого игрока по SteamID')
            values['target_steam'] = target
        for key, default, low, high, integer in (
            ('count', 1, 1, 20 if action == 'SpawnMob' else 500, True),
            ('radius', 5, 1, 40, False), ('height', 1, .1, 8, False),
            ('x', 0, -10500, 10500, False), ('y', 0, -10000, 10000, False),
            ('z', 0, -10500, 10500, False), ('hammer_targets', 15, 0, 15, True)):
            number = data.get(key, default)
            if (type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high
                    or integer and type(number) is not int):
                raise ValueError('Недопустимое числовое значение игровой команды: ' + key)
            values[key] = str(number)
        enabled = data.get('enabled', False)
        if type(enabled) is not bool:
            raise ValueError('Параметр enabled должен быть логическим')
        values['enabled'] = 'true' if enabled else 'false'
        for key, limit in (('prefab', 160), ('text', 300)):
            text = data.get(key, '')
            if not isinstance(text, str) or len(text) > limit or any(ord(c) < 32 for c in text):
                raise ValueError('Недопустимый текст игровой команды: ' + key)
            values[key] = text
        if action in ('SpawnItem', 'SpawnMob') and not values['prefab']:
            raise ValueError('Выберите игровой объект из каталога')
        role = data.get('role', 'None')
        if role not in ('None', 'Moderator', 'Builder'):
            raise ValueError('Владельца назначают в разделе «Игроки»')
        values['role'] = role
        if action == 'TeleportSaved':
            point_id = data.get('point_id')
            if not isinstance(point_id, str) or not HEX.fullmatch(point_id):
                raise ValueError('Выберите сохранённую точку игрока')
            values['point_id'] = point_id
        if (action == 'HammerStrike' or action == 'HammerToggle' and enabled) and values['hammer_targets'] == '0':
            raise ValueError('Выберите хотя бы одну цель молота')
        return values

    def submit(self, data):
        values = self.validate(data)
        status = self.view()
        if not status['available']:
            raise ValueError(status['message'])
        if values['session'] != status['session']:
            raise ValueError('Мир или процесс сервера изменился. Обновите список игроков.')
        players = {p['steam_id']: p for p in status['players']}
        actor = players.get(values['actor_steam'])
        if not actor or not actor['ready']:
            raise ValueError('У исполнителя нет совместимого клиентского админ-мода')
        if values['action'] in TARGET_ACTIONS and values['target_steam'] not in players:
            raise ValueError('Целевой игрок уже отключился от сервера')
        now = time.time()
        for identifier, request in list(self.requests.items()):
            if request['expires'] < now - 300:
                self.requests.pop(identifier)
                for prefix in ('command', 'result'):
                    (self.root / f'{prefix}-{identifier}.xml').unlink(missing_ok=True)
        if sum(r['expires'] > now and not r.get('terminal') for r in list(self.requests.values())) >= 16:
            raise ValueError('Слишком много игровых команд. Дождитесь результата.')
        identifier = secrets.token_hex(16)
        expires = now + 30
        values.update(id=identifier, expires=str(expires))
        # Record the attempt before publishing work: a logging/storage failure
        # must not leave an executable command behind an HTTP failure.
        self.manager.store.event('game-admin', 'Hearth: ' + values['action'] + ' · Steam_' + values['actor_steam'])
        _atomic(self.root / f'command-{identifier}.xml', ET.Element('command', values))
        self.requests[identifier] = {'expires': expires, 'session': values['session']}
        return {'id': identifier, 'state': 'pending'}

    def result(self, identifier):
        if not isinstance(identifier, str) or not HEX.fullmatch(identifier):
            raise ValueError('Игровая команда не найдена')
        request = self.requests.get(identifier)
        if request is None:
            raise ValueError('Игровая команда не найдена')
        path = self.root / f'result-{identifier}.xml'
        try:
            root = _xml(path)
            if root.tag != 'result' or root.get('id') != identifier or root.get('session') != request['session']:
                raise ValueError('Ответ относится к другой игровой команде')
            request['terminal'] = True
            return {'id': identifier, 'state': 'done' if root.get('success') == 'true' else 'error',
                    'message': root.get('message', '')[:2000], 'message_en': root.get('message_en', root.get('message', ''))[:2000]}
        except OSError:
            pass
        except ValueError:
            if path.exists():
                raise
        # Maintenance can disable new submissions while an accepted command is
        # still in flight. Missing/stale telemetry is not proof of a new world.
        try:
            current = self._status()
        except (OSError, ValueError):
            current = None
        if current is not None and current.get('session') != request['session']:
            request['terminal'] = True
            (self.root / f'command-{identifier}.xml').unlink(missing_ok=True)
            return {'id': identifier, 'state': 'error', 'message': 'Игровая сессия завершилась. Команда не будет повторена.'}
        if time.time() > request['expires']:
            request['terminal'] = True
            (self.root / f'command-{identifier}.xml').unlink(missing_ok=True)
            return {'id': identifier, 'state': 'error', 'message': 'Нет подтверждения клиента. Результат неизвестен; проверьте игру перед повтором.'}
        return {'id': identifier, 'state': 'pending'}
