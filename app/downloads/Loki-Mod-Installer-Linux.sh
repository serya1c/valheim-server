#!/bin/sh
# Loki / Steam Proton. Run as your user: bash Loki-Mod-Installer-Linux.sh
if ! command -v python3 >/dev/null 2>&1; then
    echo "Нужен Python 3.9 или новее. Установите python3 средствами своего дистрибутива." >&2
    exit 1
fi
exec python3 -c 'import sys; sys.version_info >= (3,9) or sys.exit("Нужен Python 3.9 или новее"); p=sys.argv[1]; sys.argv=sys.argv[1:]; exec(compile(open(p,encoding="utf-8").read().split("# LOKI_PYTHON_SOURCE\n",1)[1],p,"exec"))' "$0" "$@"
exit 1
# LOKI_PYTHON_SOURCE
#!/usr/bin/env python3
"""Loki installer for the Windows Steam client running under Proton. Python 3.9+."""
import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

SERVER = 'https://loki.ach-play.ru/api/public'
LAUNCH = 'WINEDLLOVERRIDES="winhttp=n,b" %command%'
KNOWN_HASH = '1f6f1944b2285c34d663cbaf4353c846cabd4c35b9549d9006dd302ee4bda79b'
VERSION = re.compile(r'\d+\.\d+\.\d+(?:\.\d+)?')
REQUIRED = {'winhttp.dll', 'doorstop_config.ini', 'BepInEx/core/BepInEx.dll', 'BepInEx/plugins/ValheimPlus.dll'}


def vdf(text):
    tokens = re.findall(r'"((?:\\.|[^"\\])*)"|([{}])|([^\s"{}]+)', re.sub(r'//[^\n]*', '', text))
    words = [re.sub(r'\\([\\"])', r'\1', a) if not b and not c else b or c for a, b, c in tokens]
    pos = 0
    def read(nested=False, depth=0):
        nonlocal pos
        if depth > 32:
            raise ValueError('Слишком глубокий VDF Steam.')
        out = {}
        while pos < len(words):
            key = words[pos]; pos += 1
            if key == '}':
                if not nested: raise ValueError('Некорректный VDF Steam.')
                return out
            if key == '{' or pos >= len(words): raise ValueError('Некорректный VDF Steam.')
            val = words[pos]; pos += 1
            if val == '}': raise ValueError('Некорректный VDF Steam.')
            out[key.lower()] = read(True, depth+1) if val == '{' else val
        if nested: raise ValueError('Незакрытый VDF Steam.')
        return out
    return read()


def find_games(home=None):
    home = Path(home or Path.home())
    roots = [home/'.steam/steam', home/'.steam/root', home/'.local/share/Steam',
             home/'.var/app/com.valvesoftware.Steam/.local/share/Steam', home/'snap/steam/common/.local/share/Steam']
    if not home.is_absolute(): raise ValueError('Нужен абсолютный путь домашней папки.')
    xdg = os.environ.get('XDG_DATA_HOME')
    if xdg and Path(xdg).is_absolute(): roots.append(Path(xdg)/'Steam')
    libraries = {p.resolve() for p in roots if p.is_dir()}
    for root in list(libraries):
        try:
            folders = vdf((root/'steamapps/libraryfolders.vdf').read_text(encoding='utf-8-sig'))['libraryfolders']
            for key, value in folders.items():
                if key.isdigit():
                    path = value.get('path') if isinstance(value, dict) else value
                    if isinstance(path, str) and Path(path).is_absolute(): libraries.add(Path(path).resolve())
        except (OSError, ValueError, KeyError, AttributeError): pass
    found = set()
    for library in libraries:
        try:
            app = vdf((library/'steamapps/appmanifest_892970.acf').read_text(encoding='utf-8-sig'))['appstate']
            name = app['installdir']
            if app['appid'] != '892970' or not isinstance(name, str) or not name or name in {'.','..'} or any(c in name for c in '/\\\0'): continue
            game = (library/'steamapps/common'/name).resolve()
            if (game/'valheim.exe').is_file() and (game/'valheim_Data').is_dir(): found.add(game)
        except (OSError, ValueError, KeyError, TypeError): pass
    return sorted(found)


def safe(root, relative):
    """Resolve Steam root aliases once; never follow links within an installation."""
    root = Path(root).resolve()
    parts = relative.replace('\\', '/').split('/')
    if any(not p or p in {'.','..'} or p[-1:] in {' ','.'} or any(c in p for c in ':\0<>"|?*') or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', p, re.I) for p in parts):
        raise ValueError('Недопустимый путь: '+relative)
    target = root
    for part in parts:
        if target.is_dir():
            # Windows/Proton treats case differently from Linux: refuse ambiguous trees.
            if any(p.name.casefold() == part.casefold() and p.name != part for p in target.iterdir()):
                raise ValueError('Разный регистр имён в папке: '+str(target/part))
        target = target/part
        if target.is_symlink(): raise ValueError('Ссылка внутри папки игры: '+str(target))
        if target.exists() and not (target.is_file() or target.is_dir()): raise ValueError('Особый файл: '+str(target))
    return target


def allowed(name):
    return name in {'.doorstop_version', 'doorstop_config.ini', 'winhttp.dll', 'BepInEx', 'doorstop_libs'} or name.startswith(('BepInEx/', 'doorstop_libs/'))


def game_closed(proc=Path('/proc')):
    for p in proc.glob('[0-9]*/comm'):
        try:
            if p.read_text().strip().lower() in {'valheim.exe', 'valheim', 'valheim.x86_64'}:
                raise RuntimeError('Закройте Valheim перед установкой или восстановлением.')
        except (FileNotFoundError, ProcessLookupError): pass
        except PermissionError:
            # Other users' processes can be private; own processes must be inspectable.
            if p.stat().st_uid == os.getuid(): raise RuntimeError('Не удалось проверить запущенные процессы.')


def pe(path):
    with Path(path).open('rb') as f:
        if f.read(2) != b'MZ': raise ValueError('Ожидался Windows-файл: '+str(path))
        f.seek(0x3c); offset = f.read(4)
        if len(offset) != 4: raise ValueError('Повреждён PE-файл.')
        f.seek(struct.unpack('<I', offset)[0])
        if f.read(4) != b'PE\0\0': raise ValueError('Повреждён PE-файл.')
        machine = f.read(2)
        if machine not in {b'\x64\x86', b'\x4c\x01'}: raise ValueError('Неподдерживаемая архитектура PE.')
        return machine


def validate_game(game):
    game = Path(game).expanduser().resolve(strict=True)
    if not safe(game, 'valheim_Data').is_dir() or not safe(game, 'valheim.exe').is_file():
        raise ValueError('Нужна Windows-версия Valheim: valheim.exe и valheim_Data. Включите Proton в свойствах игры и дождитесь загрузки Steam.')
    if pe(game/'valheim.exe') != b'\x64\x86': raise ValueError('Нужен Windows-клиент Valheim x64.')
    if safe(game, 'BepInEx/core/BepInEx.Core.dll').exists(): raise ValueError('Найден BepInEx 6. Нужна отдельная чистая установка игры с BepInEx 5.')
    plugins = safe(game, 'BepInEx/plugins')
    if plugins.is_dir():
        for parent, dirs, files in os.walk(plugins, followlinks=False):
            for name in dirs + files:
                item = safe(game, (Path(parent)/name).relative_to(game).as_posix())
                if item.suffix.lower() == '.dll' and item != plugins/'ValheimPlus.dll':
                    if 'valheimplus' in name.lower() or b'ValheimPlus\0' in item.read_bytes():
                        raise ValueError('Найдена другая копия или зависимый от V+ мод: '+str(item)+'. Проверьте совместимость и уберите конфликт перед установкой.')
    game_closed()
    return game


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


def server_endpoint(website):
    u = urllib.parse.urlsplit(website)
    if u.scheme != 'https' or not u.hostname or u.port not in {None,443} or u.username or u.password or u.path not in {'','/'} or u.query or u.fragment or '\\' in website or any(c.isspace() for c in website):
        raise ValueError('Укажите HTTPS-адрес сайта сервера без пути, параметров и пароля (порт 443).')
    return website.rstrip('/') + '/api/public'


def fetch(url, limit=1024*1024):
    hosts = {'api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'}
    opener = urllib.request.build_opener(NoRedirect())
    is_server = url == SERVER
    original = urllib.parse.urlsplit(SERVER).netloc
    if is_server: hosts = {urllib.parse.urlsplit(SERVER).hostname}
    for _ in range(6):
        u = urllib.parse.urlsplit(url)
        if u.scheme != 'https' or u.hostname not in hosts or u.port not in {None,443} or u.username or u.password or (is_server and u.netloc != original):
            raise ValueError('Неожиданный источник загрузки.')
        try:
            response = opener.open(urllib.request.Request(url, headers={'User-Agent':'Loki-Proton-Installer/1.0','Cache-Control':'no-cache'}), timeout=30)
        except urllib.error.HTTPError as e:
            if e.code in {301,302,303,307,308} and e.headers.get('Location'):
                url = urllib.parse.urljoin(url, e.headers['Location']); e.close(); continue
            raise RuntimeError('Источник загрузки ответил HTTP '+str(e.code)) from None
        with response:
            result = bytearray(); deadline = time.monotonic()+180
            while True:
                chunk = response.read(65536)
                if not chunk: return bytes(result)
                result.extend(chunk)
                if len(result)>limit or time.monotonic()>deadline: raise ValueError('Превышен размер или время загрузки.')
    raise ValueError('Слишком много перенаправлений.')


def server_version():
    data = json.loads(fetch(SERVER))
    if data.get('mode') == 'vanilla': raise ValueError('Это ванильный сервер. V+ не требуется; используйте клиент без модов.')
    game, mod = data.get('game'), data.get('mod')
    if not all(isinstance(v,str) and VERSION.fullmatch(v) for v in [game,mod]):
        raise ValueError('Сервер ещё не сообщает установленные версии. Повторите позже.')
    return game, mod


def release_asset(data, mod):
    if data.get('tag_name') != mod or data.get('draft') is not False or data.get('prerelease') is not False:
        raise ValueError('Релиз не соответствует версии сервера.')
    assets = [a for a in data.get('assets',[]) if a.get('name') == 'WindowsClient.zip']
    if len(assets) != 1: raise ValueError('Нет однозначного WindowsClient.zip у версии сервера.')
    a = assets[0]; url = a.get('browser_download_url')
    if url != f'https://github.com/Grantapher/ValheimPlus/releases/download/{mod}/WindowsClient.zip': raise ValueError('Неожиданный адрес пакета.')
    digest = KNOWN_HASH if mod == '0.10.2.0' else str(a.get('digest','')).removeprefix('sha256:')
    if not re.fullmatch('[0-9a-fA-F]{64}',digest): raise ValueError('Нет SHA-256 пакета. Установка отменена.')
    return url, digest.lower()


def download(mod):
    url, digest = release_asset(json.loads(fetch(f'https://api.github.com/repos/Grantapher/ValheimPlus/releases/tags/{mod}')),mod)
    data = fetch(url,128*1024*1024)
    if hashlib.sha256(data).hexdigest() != digest: raise ValueError('SHA-256 пакета не совпадает.')
    return data


def extract(data, stage):
    files=[]; seen=set()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if len(z.infolist())>5000 or sum(i.file_size for i in z.infolist())>512*1024*1024: raise ValueError('Архив слишком большой.')
        for i in z.infolist():
            name=i.filename.replace('\\','/').rstrip('/')
            if not name or not allowed(name): raise ValueError('Неожиданный файл в архиве: '+name)
            if name.casefold() in seen: raise ValueError('Повтор пути в архиве.')
            seen.add(name.casefold())
            mode=stat.S_IFMT(i.external_attr >> 16)
            if mode not in {0,stat.S_IFREG,stat.S_IFDIR} or i.external_attr & 0x400: raise ValueError('Ссылки и особые файлы в архиве запрещены.')
            dest=safe(stage,name)
            if i.is_dir(): dest.mkdir(parents=True,exist_ok=True); continue
            dest.parent.mkdir(parents=True,exist_ok=True)
            with z.open(i) as source, dest.open('xb') as target: shutil.copyfileobj(source,target)
            files.append(name)
    if not REQUIRED.issubset(files): raise ValueError('Клиентский пакет неполон.')
    for name in REQUIRED:
        if name.endswith('.dll'): pe(safe(stage,name))
    return files


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(65536),b''): h.update(block)
    return h.hexdigest()


def atomic_copy(source, target):
    target.parent.mkdir(parents=True,exist_ok=True)
    fd, tmp=tempfile.mkstemp(prefix='.loki-',dir=target.parent)
    try:
        with os.fdopen(fd,'wb') as out, source.open('rb') as inp:
            shutil.copyfileobj(inp,out); out.flush(); os.fsync(out.fileno())
        os.chmod(tmp, stat.S_IMODE(source.stat().st_mode))
        os.replace(tmp,target)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def save_journal(folder,journal):
    tmp=safe(folder,'journal.tmp'); target=safe(folder,'journal.json')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(journal,f,ensure_ascii=False,indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,target)


def latest(game):
    root=safe(game,'.loki-installer-linux/backups')
    folders=[]
    if root.is_dir():
        for p in root.iterdir():
            safe(game,p.relative_to(game).as_posix())
            if p.is_dir() and safe(p,'journal.json').is_file(): folders.append(p)
    return max(folders,default=None)


@contextlib.contextmanager
def lock(game):
    base=safe(game,'.loki-installer-linux'); base.mkdir(exist_ok=True)
    with safe(base,'install.lock').open('a') as f:
        try: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('Уже работает другой установщик Loki.') from None
        yield


def read_journal(backup):
    return json.loads(safe(backup,'journal.json').read_text(encoding='utf-8'))


def restore_files(game,backup,journal):
    if journal.get('game') != str(game) or not isinstance(journal.get('files'),list) or len(journal['files'])>5000:
        raise ValueError('Копия не относится к этой папке игры.')
    seen=set()
    for item in journal['files']:
        name=item['path']
        if not allowed(name) or name.casefold() in seen: raise ValueError('Некорректный журнал копии.')
        seen.add(name.casefold()); target=safe(game,name)
        if target.exists() and digest(target) not in {item['installed'], item['original']}:
            raise ValueError('Файл изменён после установки; восстановление отменено: '+name)
        if item['original'] is not None and digest(safe(backup,'original/'+name)) != item['original']:
            raise ValueError('Повреждена резервная копия: '+name)
    for item in journal['files']:
        game_closed(); target=safe(game,item['path'])
        if item['original'] is not None: atomic_copy(safe(backup,'original/'+item['path']),target)
        elif target.exists(): target.unlink()
    journal['state']='restored'; save_journal(backup,journal)


def restore(game):
    game=validate_game(game)
    with lock(game):
        backup=latest(game)
        if backup is None: raise ValueError('Резервной копии Linux-установщика нет.')
        journal=read_journal(backup)
        if journal['state']=='restored': raise ValueError('Последняя установка уже отменена.')
        restore_files(game,backup,journal)
        return backup


def install(game,stage,files,mod,log=print,before_copy=None):
    game=validate_game(game)
    with lock(game):
        previous=latest(game)
        if previous and read_journal(previous)['state']=='installing': raise ValueError('Предыдущая установка прервана. Сначала выполните восстановление.')
        backup=safe(game,'.loki-installer-linux/backups/'+str(time.time_ns())+'-'+uuid.uuid4().hex)
        backup.mkdir(parents=True)
        journal={'game':str(game),'mod':mod,'state':'installing','files':[]}
        for name in files:
            if not allowed(name): raise ValueError('Недопустимый файл установки.')
            target=safe(game,name); source=safe(stage,name)
            if name.startswith('BepInEx/config/') and target.is_file():
                log('Сохранена конфигурация: '+name); continue
            original=digest(target) if target.is_file() else None
            if original is not None:
                saved=safe(backup,'original/'+name); atomic_copy(target,saved)
                if digest(saved)!=original: raise ValueError('Ошибка резервного копирования.')
            journal['files'].append({'path':name,'original':original,'installed':digest(source)})
        save_journal(backup,journal)
        try:
            for index,item in enumerate(journal['files']):
                game_closed()
                if before_copy: before_copy(index)
                atomic_copy(safe(stage,item['path']),safe(game,item['path']))
            journal['state']='installed'; save_journal(backup,journal)
        except BaseException as error:
            try: restore_files(game,backup,journal)
            except BaseException as rollback_error:
                raise RuntimeError('Откат не завершён. Копия: '+str(backup)+'. '+str(rollback_error)) from error
            log('Прежние файлы восстановлены после ошибки.'); raise
        return backup


def launch_help():
    print('\nВ Steam: Valheim → Свойства → Совместимость → включите Proton.')
    print('Свойства → Общие → Параметры запуска:')
    print('\n  '+LAUNCH+'\n')
    print('Если уже есть параметры, не стирайте их. Добавьте winhttp=n,b в существующий')
    print('WINEDLLOVERRIDES через точку с запятой; %command% должен остаться один раз.')
    print('При использовании mangohud/gamemoderun переменную укажите перед ними.')
    print('Steam Flatpak: задавайте параметр внутри Steam; Protontricks не нужен.')


def main(argv=None):
    global SERVER
    parser=argparse.ArgumentParser(description='Установщик Loki для Steam / Proton (Linux x86_64). Без sudo.')
    parser.add_argument('--server',default='https://loki.ach-play.ru',help='HTTPS-адрес сайта нужного сервера')
    parser.add_argument('--game',help='Папка Windows-версии Valheim')
    parser.add_argument('--restore',action='store_true',help='Восстановить файлы до последней установки')
    parser.add_argument('--launch-options',action='store_true',help='Показать настройки Proton')
    args=parser.parse_args(argv)
    SERVER=server_endpoint(args.server)
    if args.launch_options: launch_help(); return 0
    if platform.system()!='Linux' or platform.machine().lower() not in {'x86_64','amd64'}:
        raise ValueError('Нужен Linux x86_64. Для Windows есть отдельный EXE.')
    if os.geteuid()==0: raise ValueError('Запускайте от своего пользователя, без sudo/root.')
    print('ᛟ LOKI — подготовка к приключению / Steam + Proton\n')
    if not sys.stdin.isatty(): raise ValueError('Откройте терминал и запустите: bash Loki-Mod-Installer-Linux.sh')
    if args.game: game=Path(args.game).expanduser()
    else:
        games=find_games()
        for n,p in enumerate(games,1): print(f'  {n}. {p}')
        choice=input('Номер папки из списка или полный путь к Valheim: ').strip()
        game=games[int(choice)-1] if choice.isdigit() and 1<=int(choice)<=len(games) else Path(choice).expanduser()
    game=validate_game(game)
    if args.restore:
        print('Будут восстановлены файлы до последней установки в '+str(game))
        if input('Продолжить? [да/нет]: ').strip().lower() not in {'да','yes','y'}: return 0
        print('Восстановлено из: '+str(restore(game)))
        print('Параметры запуска Steam не менялись. Если BepInEx удалён, уберите только winhttp из WINEDLLOVERRIDES.')
        return 0
    version=server_version()
    print(f'На {args.server}: Valheim {version[0]}, V+ {version[1]}. Игру обновляет Steam.')
    print('Папка: '+str(game))
    print('Существующие конфигурации сохранятся; заменяемые файлы будут скопированы в резервную копию.')
    if input('Установить мод? [да/нет]: ').strip().lower() not in {'да','yes','y'}: return 0
    print('Загружаем WindowsClient.zip от Grantapher для Proton…')
    data=download(version[1]); print('SHA-256 проверен.')
    with tempfile.TemporaryDirectory(prefix='loki-proton-') as folder:
        stage=Path(folder); files=extract(data,stage)
        if server_version()!=version: raise ValueError('Сервер обновился во время загрузки. Повторите установку.')
        backup=install(game,stage,files,version[1])
    print('Файлы мода установлены. Резервная копия: '+str(backup))
    launch_help()
    print('\nПосле настройки запустите игру через Steam. В BepInEx/LogOutput.log должна появиться загрузка Valheim Plus.')
    print('Адрес подключения и сообщество: '+args.server)
    return 0


if __name__=='__main__':
    try: sys.exit(main())
    except KeyboardInterrupt: print('\nОперация отменена.',file=sys.stderr); sys.exit(1)
    except Exception as e: print('Ошибка: '+str(e),file=sys.stderr); sys.exit(1)
