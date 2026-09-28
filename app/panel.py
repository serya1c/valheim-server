"""Host-level panel configuration, intentionally outside game backup archives."""
import hashlib
import hmac
import json
import os
import secrets
from configuration import clean_text


def password_hash(password):
    clean_text(password, 'Пароль администратора', 16, 256)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return {'salt': salt.hex(), 'hash': digest.hex()}


class Panel:
    def __init__(self, base):
        self.path = base / 'panel.json'

    @property
    def configured(self):
        return self.path.is_file()

    def load(self):
        if self.configured:
            return json.loads(self.path.read_text(encoding='utf-8'))
        return {'backup_hours': 6, 'backup_keep': 12, 'cookie_secure': False}

    def save(self, data):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    def verify(self, password):
        if not self.configured or not isinstance(password, str) or len(password) > 256:
            return False
        auth = self.load()['auth']
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(auth['salt']), n=16384, r=8, p=1)
        return hmac.compare_digest(digest.hex(), auth['hash'])

    def revision(self):
        return hashlib.sha256(json.dumps(self.load(), sort_keys=True).encode()).hexdigest()

    def view(self):
        return {k: v for k, v in self.load().items() if k != 'auth'}

    @staticmethod
    def validate(values):
        if not isinstance(values, dict) or set(values) - {'backup_hours', 'backup_keep', 'cookie_secure'}:
            raise ValueError('Неизвестные настройки панели')
        for key, low, high in [('backup_hours', 0, 720), ('backup_keep', 1, 1000)]:
            if type(values.get(key)) is not int or not low <= values[key] <= high:
                raise ValueError(f'{key}: целое число от {low} до {high}')
        if type(values.get('cookie_secure')) is not bool:
            raise ValueError('Для HTTPS требуется переключатель')
        return values
