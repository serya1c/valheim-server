"""Persistent, validated panel configuration and lossless BepInEx CFG editing."""
import copy
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

LANDING_DEFAULTS = {'title':'Loki', 'address':'loki.ach-play.ru:2456', 'community_url':'http://discord.ach-play.ru',
    'description':'Собери друзей у очага. Построй первый дом, подними паруса и отправляйся навстречу неизведанному. В этом мире найдётся место для твоей истории.'}
PROJECT_URL = 'https://loki.ach-play.ru'


def listing_required():
    return os.getenv('REQUIRE_PUBLIC_LISTING', '1') == '1'

PRESETS = {'normal':'Обычный', 'casual':'Беззаботный', 'easy':'Лёгкий', 'hard':'Сложный',
           'hardcore':'Хардкор', 'immersive':'Погружение', 'hammer':'Строительство'}
MODIFIERS = {
    'combat': ('Сложность боя', {'':'Из набора правил','veryeasy':'Очень легко','easy':'Легко','hard':'Сложно','veryhard':'Очень сложно'}),
    'deathpenalty': ('Штраф за смерть', {'':'Из набора правил','casual':'Минимальный','veryeasy':'Очень мягкий','easy':'Мягкий','hard':'Суровый','hardcore':'Хардкор'}),
    'resources': ('Количество ресурсов', {'':'Из набора правил','muchless':'Намного меньше','less':'Меньше','more':'Больше','muchmore':'Намного больше','most':'Максимум'}),
    'raids': ('Частота рейдов', {'':'Из набора правил','none':'Отключены','muchless':'Намного реже','less':'Реже','more':'Чаще','muchmore':'Намного чаще'}),
    'portals': ('Правила порталов', {'':'Из набора правил','casual':'Перенос любых предметов','hard':'Без переноса предметов','veryhard':'Порталы отключены'}),
}
WORLD_KEYS = {'nobuildcost':'Строительство без затрат', 'playerevents':'Рейды по прогрессу игроков',
              'passivemobs':'Пассивные противники', 'nomap':'Отключить карту'}


def atomic_text(path, text):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8', newline='')
    tmp.replace(path)


def default_world():
    return {'managed':False, 'preset':'normal', 'modifiers':{k:'' for k in MODIFIERS}, 'keys':[]}


def clean_text(value, label, minimum=0, maximum=120):
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or any(ord(c) < 32 for c in value):
        raise ValueError(f'{label}: недопустимая длина или управляющие символы')
    return value


def world_name(value):
    clean_text(value, 'Имя мира', 1, 80)
    if value != value.strip() or not re.fullmatch(r'[\w -]+', value):
        raise ValueError('Имя мира: буквы, цифры, пробел, дефис и подчёркивание; без пробелов по краям')
    return value


def cfg_entries(text):
    """Keep line indices so comments, ordering and unknown fields survive edits."""
    entries, seen, section, comments = [], set(), '', []
    for index, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if not stripped or stripped.startswith(('#',';')):
            comments.append(stripped)
            continue
        if re.fullmatch(r'\[[^\]\r\n]+\]', stripped):
            section, comments = stripped[1:-1], []
            continue
        match = re.fullmatch(r'\s*([^=\r\n]+?)\s*=\s*(.*?)\s*', line)
        if not match or not section:
            raise ValueError(f'Конфигурация мода: ошибка синтаксиса в строке {index+1}')
        key, value = match.groups()
        ident = section + '/' + key
        if ident in seen:
            raise ValueError(f'Повтор параметра {ident}')
        seen.add(ident)
        metadata = '\n'.join(comments)
        description = '\n'.join(c[3:] for c in comments if c.startswith('## '))
        declared = re.search(r'Setting type:\s*(\w+)', metadata)
        options = re.search(r'Acceptable values:\s*(.+)', metadata)
        bounds = re.search(r'Acceptable value range:\s*From\s+([\d.eE+-]+)\s+to\s+([\d.eE+-]+)', metadata)
        default = re.search(r'Default value:\s*(.*)', metadata)
        kind = 'text'
        if declared:
            kind = {'Boolean':'bool','Int32':'int','Int64':'int','UInt32':'int',
                    'Single':'float','Double':'float','Decimal':'float'}.get(declared[1], 'text')
        elif value.lower() in ('true','false'):
            kind = 'bool'
        elif re.fullmatch(r'[+-]?\d+', value):
            kind = 'int'
        elif re.fullmatch(r'[+-]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][+-]?\d+)?', value):
            kind = 'float'
        entries.append({'id':ident, 'section':section, 'key':key, 'value':value, 'kind':kind,
            'options': [s.strip() for s in options[1].split(',')] if options else [],
            'min':float(bounds[1]) if bounds else None, 'max':float(bounds[2]) if bounds else None,
            'default':default[1] if default else None, 'description':description, 'line':index})
        comments = []
    return entries


def validate_value(entry, value):
    clean_text(value, entry['id'], maximum=2048)
    if entry['kind'] == 'bool' and value not in ('true','false'):
        raise ValueError(f"{entry['id']}: выберите да или нет")
    if entry['options'] and value not in entry['options']:
        raise ValueError(f"{entry['id']}: значение отсутствует в списке допустимых")
    if entry['kind'] in ('int','float'):
        if entry['kind'] == 'int' and not re.fullmatch(r'[+-]?\d+', value):
            raise ValueError(f"{entry['id']}: требуется целое число")
        try:
            number = float(value)
        except ValueError:
            raise ValueError(f"{entry['id']}: требуется число с точкой") from None
        if not math.isfinite(number):
            raise ValueError(f"{entry['id']}: недопустимое число")
        if entry['kind'] == 'int' and not -(2**31) <= number <= 2**31-1:
            raise ValueError(f"{entry['id']}: слишком большое целое число")
        if entry['min'] is not None and number < entry['min'] or entry['max'] is not None and number > entry['max']:
            raise ValueError(f"{entry['id']}: значение вне допустимого диапазона")
    return value


def edit_cfg(text, values):
    if not isinstance(values, dict):
        raise ValueError('Ожидается список параметров мода')
    entries = {e['id']:e for e in cfg_entries(text)}
    if values.keys() - entries.keys():
        raise ValueError('Неизвестные параметры мода; перечитайте конфигурацию')
    lines = text.splitlines(keepends=True)
    for ident, value in values.items():
        e = entries[ident]
        validate_value(e, value)
        original = lines[e['line']]
        ending = '\r\n' if original.endswith('\r\n') else '\n' if original.endswith('\n') else ''
        prefix = original.split('=',1)[0] + '= '
        lines[e['line']] = prefix + value + ending
    return ''.join(lines)


class Configuration:
    def __init__(self, base):
        self.base = base
        self.path = base / 'config/hearth-settings.json'

    def load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            data['landing'] = {**LANDING_DEFAULTS, **data.get('landing', {})}
            return data
        name = os.getenv('WORLD_NAME','North')
        return {'server': {'name':os.getenv('SERVER_NAME','Loki'), 'password':os.getenv('SERVER_PASSWORD',''),
            'public':os.getenv('SERVER_PUBLIC','1') == '1', 'saveinterval':1800, 'backups':4,
            'backupshort':7200, 'backuplong':43200}, 'world_name':name, 'worlds':{name:default_world()}, 'landing':dict(LANDING_DEFAULTS)}

    def mod_path(self):
        for name in ('org.bepinex.plugins.valheim_plus.cfg', 'valheim_plus.cfg'):
            p = self.base / 'config' / name
            if p.is_file():
                return p
        return None

    def advertised_name(self):
        name = self.load()['server']['name']
        if not listing_required():
            return name
        if PROJECT_URL in name:
            return name
        return name[:80-len(PROJECT_URL)-3].rstrip() + ' | ' + PROJECT_URL

    def mod_text(self):
        p = self.mod_path()
        return p.read_bytes().decode('utf-8-sig') if p else ''

    @staticmethod
    def fingerprint(settings, text):
        raw = json.dumps(settings, sort_keys=True, ensure_ascii=False) + '\0' + text
        return hashlib.sha256(raw.encode()).hexdigest()

    def revision(self):
        return self.fingerprint(self.load(), self.mod_text())

    def view(self):
        data = copy.deepcopy(self.load())
        text = self.mod_text()
        revision = self.fingerprint(data, text)
        data['server']['password_set'] = bool(data['server'].pop('password'))
        if listing_required():
            data['server']['public'] = True
        names = set(data['worlds'])
        folder = self.base / 'saves/worlds_local'
        if folder.exists():
            for p in folder.iterdir():
                candidate = p.name if p.is_dir() else p.stem if p.suffix == '.fwl' else None
                if candidate:
                    with contextlib.suppress(ValueError):
                        names.add(world_name(candidate))
        path = self.mod_path()
        return {**data, 'revision':revision, 'world_names':sorted(names),
            'listing_required':listing_required(), 'advertised_name':self.advertised_name(),
            'presets':PRESETS, 'modifiers':MODIFIERS, 'world_keys':WORLD_KEYS,
            'mod':{'available':bool(path), 'filename':path.name if path else None, 'entries':cfg_entries(text)}}

    def prepare(self, data):
        if data.get('revision') != self.revision():
            raise ValueError('Конфигурация уже изменилась. Нажмите «Перечитать» и повторите изменения.')
        settings = copy.deepcopy(self.load())
        scope = data.get('scope')
        values = data.get('values')
        if not isinstance(values, dict):
            raise ValueError('Некорректные параметры')
        if scope == 'server':
            s = settings['server']
            allowed = set(s)
            if values.keys() - allowed:
                raise ValueError('Неизвестный параметр сервера')
            s.update(values)
            if not s['password']:
                s['password'] = self.load()['server']['password']
            s['name'] = clean_text(s['name'], 'Название сервера', 1, 80).strip()
            clean_text(s['password'], 'Пароль игры', 5, 128)
            if not s['name'] or s['password'].casefold() in s['name'].casefold():
                raise ValueError('Название пустое или содержит пароль игры')
            if type(s['public']) is not bool:
                raise ValueError('Видимость сервера: ожидается переключатель')
            if listing_required():
                s['public'] = True
                if s['password'].casefold() in PROJECT_URL.casefold():
                    raise ValueError('Пароль игры не должен совпадать с частью адреса сайта в имени сервера')
            for key, low, high in [('saveinterval',60,86400),('backups',1,100),('backupshort',60,604800),('backuplong',60,2592000)]:
                if type(s[key]) is not int or not low <= s[key] <= high:
                    raise ValueError(f'{key}: требуется целое число от {low} до {high}')
        elif scope == 'world':
            name = world_name(values.get('name'))
            w = values.get('rules')
            if not isinstance(w, dict) or set(w) != {'managed','preset','modifiers','keys'}:
                raise ValueError('Неполные правила мира')
            if type(w['managed']) is not bool or w['preset'] not in PRESETS:
                raise ValueError('Неизвестный набор правил мира')
            if not isinstance(w['modifiers'], dict) or set(w['modifiers']) != set(MODIFIERS):
                raise ValueError('Некорректный список модификаторов')
            for key, value in w['modifiers'].items():
                if value not in MODIFIERS[key][1]:
                    raise ValueError(f'Неизвестное значение {key}')
            if not isinstance(w['keys'], list) or any(k not in WORLD_KEYS for k in w['keys']) or len(set(w['keys'])) != len(w['keys']):
                raise ValueError('Некорректные переключатели мира')
            settings['world_name'] = name
            settings['worlds'][name] = w
        elif scope == 'landing':
            if values.keys() - LANDING_DEFAULTS.keys():
                raise ValueError('Неизвестный параметр лендинга')
            landing = {**settings['landing'], **values}
            for key, limit in [('title',80),('description',600),('address',260),('community_url',500)]:
                landing[key] = clean_text(landing[key], 'Лендинг: '+key, maximum=limit).strip()
            address = landing['address']
            if address:
                match = re.fullmatch(r'([a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?):(\d{1,5})', address)
                if not match or not 1 <= int(match[2]) <= 65535:
                    raise ValueError('Адрес: IPv4 или домен латиницей и порт, например play.example.com:2456')
            url = urlsplit(landing['community_url'])
            if landing['community_url'] and (url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or '\\' in landing['community_url'] or any(c.isspace() for c in landing['community_url'])):
                raise ValueError('Ссылка сообщества: полный HTTP(S)-адрес без пароля и пробелов')
            settings['landing'] = landing
        elif scope == 'mod':
            path = self.mod_path()
            if not path:
                raise ValueError('Файл V+ появится после первого запуска установленного мода')
            return path, edit_cfg(self.mod_text(), values)
        else:
            raise ValueError('Неизвестный раздел настроек')
        return self.path, json.dumps(settings, ensure_ascii=False, indent=2)

    def launch_args(self):
        data = self.load()
        s = data['server']
        name = self.advertised_name()
        if s['password'] and s['password'].casefold() in name.casefold():
            raise ValueError('Пароль игры не должен входить в публикуемое имя сервера; измените пароль в настройках')
        args = ['-name',name,'-world',data['world_name'],'-password',s['password'],
                '-public','1' if listing_required() or s['public'] else '0']
        for key in ('saveinterval','backups','backupshort','backuplong'):
            args += ['-' + key,str(s[key])]
        w = data['worlds'].get(data['world_name'], default_world())
        if w['managed']:
            args += ['-preset',w['preset']]
            for key, value in w['modifiers'].items():
                if value:
                    args += ['-modifier',key,value]
            for key in w['keys']:
                args += ['-setkey',key]
        return args
