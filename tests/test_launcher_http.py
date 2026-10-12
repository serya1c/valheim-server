"""Player downloads through the real HTTP handler, without Steam or game processes."""
import hashlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import server


class LauncherHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = server.Manager(Path(self.temp.name))
        self.manager.panel.save({**self.manager.panel.load(), 'auth': server.password_hash('fixture-only-password')})
        class Handler(server.Handler):
            manager = self.manager
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        for handler in self.manager.log.handlers[:]:
            handler.close()
            self.manager.log.removeHandler(handler)
        self.temp.cleanup()

    def get(self, path):
        connection = http.client.HTTPConnection('127.0.0.1', self.http.server_port)
        connection.request('GET', path)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_downloads_match_public_checksums_without_admin_login(self):
        status, _, body = self.get('/api/public')
        self.assertEqual(status, 200)
        metadata = json.loads(body)['launcher']
        self.assertEqual(metadata['version'], '1.1.0')
        for platform in ('windows', 'linux', 'windows_portable', 'linux_portable'):
            artifact = metadata[platform]
            status, headers, payload = self.get(artifact['url'])
            self.assertEqual(status, 200)
            self.assertEqual(len(payload), artifact['size'])
            self.assertEqual(hashlib.sha256(payload).hexdigest(), artifact['sha256'])
            self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
            self.assertIn(artifact['url'].rsplit('/', 1)[1], headers['Content-Disposition'])
            status, _, checksum = self.get(artifact['checksum_url'])
            self.assertEqual(status, 200)
            self.assertEqual(checksum.decode().split()[0], artifact['sha256'])
        self.assertEqual(metadata['windows']['url'], '/downloads/Hearth-Launcher-Setup.exe')
        self.assertEqual(metadata['linux']['url'], '/downloads/Hearth-Launcher-Install-Linux.sh')
        for path in ('/downloads/Hearth-Launcher.version', '/downloads/Hearth-Launcher-Setup.exe.config',
                     '/downloads/../server.py', '/downloads/%2e%2e/server.py'):
            self.assertNotEqual(self.get(path)[0], 200)
        self.assertEqual(self.get('/api/status')[0], 401)

    def test_landing_inserts_launcher_and_escapes_server_title(self):
        config = self.manager.config.load()
        config['landing']['title'] = '<img src=x onerror=alert(1)>'
        server.atomic_json(self.manager.config.path, config)
        status, _, body = self.get('/')
        self.assertEqual(status, 200)
        html = body.decode()
        self.assertNotIn('{{LAUNCHER_CARD}}', html)
        self.assertIn('id="launcher-downloads"', html)
        self.assertIn('bash Hearth-Launcher-Install-Linux.sh', html)
        self.assertNotIn('Loki-Mod-Installer', html)
        self.assertNotIn('Установи моды сервера', html)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', html)
        self.assertNotIn('<img src=x onerror=alert(1)>', html)


if __name__ == '__main__':
    unittest.main()
