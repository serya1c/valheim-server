"""Read Steam's dedicated-server public build without downloading game files.

Steamworks documents app_info_print and appmanifest KeyValues at
https://partner.steamgames.com/doc/sdk/uploading#Debugging_Build_Issues.
Never substitute a Steam client app ID, beta branch, or game semantic version.
"""
import contextlib
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

APP_ID = '896660'
MAX_OUTPUT = 8 * 1024 * 1024
MAX_MANIFEST = 1024 * 1024
INFO_ERROR = 'Не удалось определить последнюю сборку сервера Steam'
_BUILD = re.compile(r'[1-9][0-9]{0,19}\Z')
_APP_BLOCK = re.compile(r'(?m)^[ \t]*"896660"\s*\{')
_STEAM_ERROR = re.compile(r'\bERROR[!:]|^\s*FAILED\b|Failed to (?:connect|log[ -]?on|log[ -]?in|update app info)'
                          r'|Unable to connect|Not logged (?:on|in)|Connecting[^\r\n]*\bFAILED\b', re.I | re.M)
_OPEN, _CLOSE = object(), object()


class _KeyValues:
    """Small bounded KeyValues reader; duplicate keys are intentionally rejected."""
    def __init__(self, text, start=0):
        if not isinstance(text, str) or '\0' in text or len(text) > MAX_OUTPUT:
            raise ValueError(INFO_ERROR)
        self.text, self.position, self.tokens = text, start, 0

    def token(self):
        while self.position < len(self.text):
            char = self.text[self.position]
            if char.isspace():
                self.position += 1
            elif self.text.startswith('//', self.position):
                end = self.text.find('\n', self.position)
                self.position = len(self.text) if end < 0 else end + 1
            else:
                break
        if self.position == len(self.text):
            return None
        self.tokens += 1
        if self.tokens > 100000:
            raise ValueError(INFO_ERROR)
        char = self.text[self.position]
        self.position += 1
        if char in '{}':
            return _OPEN if char == '{' else _CLOSE
        if char == '"':
            parts = []
            while self.position < len(self.text):
                char = self.text[self.position]
                self.position += 1
                if char == '"':
                    return ''.join(parts)
                if char == '\\':
                    if self.position == len(self.text):
                        break
                    escaped = self.text[self.position]
                    self.position += 1
                    parts.append({'"': '"', '\\': '\\', 'n': '\n', 'r': '\r', 't': '\t'}.get(escaped, '\\' + escaped))
                else:
                    parts.append(char)
                if len(parts) > 65536:
                    raise ValueError(INFO_ERROR)
            raise ValueError(INFO_ERROR)
        start = self.position - 1
        while self.position < len(self.text) and not self.text[self.position].isspace() and self.text[self.position] not in '{}"':
            self.position += 1
        return self.text[start:self.position]

    def object(self, depth=0):
        if depth > 32:
            raise ValueError(INFO_ERROR)
        result = {}
        while True:
            key = self.token()
            if key is _CLOSE:
                return result
            if key is None or key is _OPEN:
                raise ValueError(INFO_ERROR)
            key = key.casefold()
            if key in result:
                raise ValueError(INFO_ERROR)
            value = self.token()
            if value is None or value is _CLOSE:
                raise ValueError(INFO_ERROR)
            result[key] = self.object(depth + 1) if value is _OPEN else value


def _build(value):
    if not isinstance(value, str) or not _BUILD.fullmatch(value):
        raise ValueError(INFO_ERROR)
    return value


def public_build_id(output):
    """Read exactly the requested app's depots/branches/public/buildid."""
    if not isinstance(output, str) or len(output) > MAX_OUTPUT:
        raise ValueError(INFO_ERROR)
    matches = list(_APP_BLOCK.finditer(output))
    if len(matches) != 1:
        raise ValueError(INFO_ERROR)
    parser = _KeyValues(output, matches[0].end())
    value = parser.object()
    # An exit status of zero alone does not prove that SteamCMD logged in or
    # refreshed successfully. Do not accept cached metadata after a known error.
    # Ordinary locale/priority warnings contain "failed" too; they are not an
    # unsuccessful app-info request.
    outside = output[:matches[0].start()] + output[parser.position:]
    if _STEAM_ERROR.search(outside):
        raise ValueError(INFO_ERROR)
    try:
        public = value['depots']['branches']['public']
        if public.get('pwdrequired', '0') != '0':
            raise ValueError(INFO_ERROR)
        return _build(public['buildid'])
    except (KeyError, TypeError, AttributeError):
        raise ValueError(INFO_ERROR) from None


def manifest_build_id(text):
    """Read a complete installation's build; incomplete/update-needed is unknown."""
    parser = _KeyValues(text)
    name = parser.token()
    if not isinstance(name, str) or name.casefold() != 'appstate' or parser.token() is not _OPEN:
        raise ValueError(INFO_ERROR)
    value = parser.object()
    if parser.token() is not None or value.get('appid') != APP_ID or value.get('stateflags') != '4':
        raise ValueError(INFO_ERROR)
    return _build(value.get('buildid'))


def installed_build_id(release):
    """Missing or unusable legacy manifests must not cause a false 'up to date'."""
    release = Path(release)
    directory = release / 'steamapps'
    path = directory / ('appmanifest_' + APP_ID + '.acf')
    try:
        if (release.is_symlink() or directory.is_symlink() or path.is_symlink()
                or not path.is_file() or not 0 < path.stat().st_size <= MAX_MANIFEST):
            return None
        with path.open('rb') as stream:
            raw = stream.read(MAX_MANIFEST + 1)
        if len(raw) > MAX_MANIFEST:
            return None
        return manifest_build_id(raw.decode('utf-8-sig'))
    except (OSError, ValueError, UnicodeError):
        return None


def _kill(process):
    if os.name == 'posix':
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    else:
        process.kill()
    process.wait(timeout=5)


def query_public_build(log=None, cancelled=None, timeout=300):
    """Metadata-only SteamCMD query. Its own cache may refresh; no app_update runs."""
    if not 0 < timeout <= 300:
        raise ValueError('Steam metadata timeout must be between 0 and 300 seconds')
    if cancelled and cancelled():
        raise RuntimeError('Проверка версий отменена: панель останавливается')
    command = ['/opt/steamcmd/steamcmd.sh', '+@ShutdownOnFailedCommand', '1',
               '+@NoPromptForPassword', '1', '+login', 'anonymous',
               '+app_info_update', '1', '+app_info_print', APP_ID, '+quit']
    environment = os.environ.copy()
    environment.pop('PANEL_PASSWORD', None)
    environment.pop('HEARTH_ADMIN_BRIDGE', None)
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                   env=environment, start_new_session=True)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if cancelled and cancelled():
                    raise RuntimeError('Проверка версий отменена: панель останавливается')
                if time.monotonic() >= deadline:
                    raise RuntimeError('SteamCMD не завершил проверку версий за отведённое время')
                if os.fstat(output.fileno()).st_size > MAX_OUTPUT:
                    raise RuntimeError(INFO_ERROR)
                time.sleep(.1)
            if process.returncode != 0 or os.fstat(output.fileno()).st_size > MAX_OUTPUT:
                raise RuntimeError(INFO_ERROR)
            output.seek(0)
            text = output.read(MAX_OUTPUT + 1).decode('utf-8', errors='replace')
            try:
                build = public_build_id(text)
            except ValueError:
                raise RuntimeError(INFO_ERROR) from None
            if log:
                log('Последняя сборка сервера Steam: ' + build)
            return build
        finally:
            if process.poll() is None:
                _kill(process)
