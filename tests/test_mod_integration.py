"""Manager transactions and HTTP boundaries, without launching game code."""
import collections
import hashlib
import http.client
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import server


def package():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('manifest.json', json.dumps({'name': 'Demo', 'version_number': '1.0.0', 'dependencies': []}))
        z.writestr('BepInEx/plugins/Demo.dll', b'MZfixture')
        z.writestr('BepInEx/config/private.cfg', 'secret=never-publish')
    return stream.getvalue()


class ModIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.manager = server.Manager(self.base)
        release = self.base / 'releases/fixture'
        release.mkdir()
        server.atomic_json(release / 'hearth.json', {'game': '1.0.16', 'mod': '0.10.2.0', 'mode': 'plus'})
        self.manager.state['active'] = 'fixture'
        self.manager.save_state()
        (self.base / 'saves/world.db').write_bytes(b'original world')

    def tearDown(self):
        for handler in self.manager.log.handlers[:]:
            handler.close()
            self.manager.log.removeHandler(handler)
        self.temp.cleanup()

    def upload(self, scope='both'):
        path = self.base / 'incoming.zip'
        path.write_bytes(package())
        self.manager.change_mods('mod_upload', {'path': str(path), 'name': 'Demo.zip', 'scope': scope})

    def test_install_backup_bundle_and_restart_persistence(self):
        self.upload()
        self.assertFalse(self.manager.running())
        self.assertEqual(len(self.manager.mods.view()['packages']), 1)
        self.assertTrue(list((self.manager.active() / 'BepInEx/plugins/HearthMods').rglob('*.dll')))
        descriptor = self.manager.public_client_mods()
        self.assertEqual(descriptor['kind'], 'overlay')
        raw = (self.base / 'client-mods.zip').read_bytes()
        self.assertEqual(descriptor['sha256'], hashlib.sha256(raw).hexdigest())
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            self.assertTrue(any(p.endswith('Demo.dll') for p in z.namelist()))
            self.assertFalse(any('private.cfg' in p for p in z.namelist()))
        backup = next((self.base / 'backups').glob('*-pre-mods.tar.gz'))
        with tarfile.open(backup) as z:
            self.assertIn('mods', z.getnames())
        other = server.Manager(self.base)
        try:
            self.assertEqual(other.public_client_mods(), descriptor)
            self.assertEqual(other.mods.view(), self.manager.mods.view())
        finally:
            for handler in other.log.handlers[:]: handler.close(); other.log.removeHandler(handler)

    def test_server_only_not_published_and_disable_removes_materialized_files(self):
        self.upload('server')
        self.assertIsNone(self.manager.public_client_mods())
        identifier = self.manager.mods.view()['packages'][0]['id']
        self.manager.change_mods('mod_toggle', {'id': identifier, 'enabled': False})
        self.assertFalse(list((self.manager.active() / 'BepInEx/plugins/HearthMods').rglob('*.dll')))

    def test_failed_download_does_not_stop_server(self):
        with patch.object(server.ModManager, 'install', side_effect=ValueError('bad package')), patch.object(self.manager, 'stop') as stop:
            with self.assertRaises(ValueError):
                self.manager.change_mods('mod_install', {'source': 'Team-Demo'})
            stop.assert_not_called()
        self.assertEqual(self.manager.mods.view()['packages'], [])

    def test_failed_start_restores_mods_and_world(self):
        proc = MagicMock(); proc.poll.return_value = None
        self.manager.proc = proc
        starts = []
        def start():
            starts.append(True)
            if len(starts) == 1: (self.base / 'saves/world.db').write_bytes(b'changed by failed mod')
            self.manager.proc = proc
        def stop(): self.manager.proc = None
        with patch.object(self.manager, 'start', side_effect=start), patch.object(self.manager, 'stop', side_effect=stop), patch.object(self.manager, 'wait_ready', side_effect=RuntimeError('broken plugin')):
            with self.assertRaisesRegex(RuntimeError, 'Изменение модов отменено'):
                self.upload()
        self.assertEqual(self.manager.mods.view()['packages'], [])
        self.assertEqual((self.base / 'saves/world.db').read_bytes(), b'original world')
        self.assertEqual(len(starts), 2)
        self.assertNotIn('mods_trial', self.manager.state)
        self.assertIsNone(self.manager.public_client_mods())

    def test_interrupted_operation_recovers_before_normal_boot(self):
        backup = self.manager.backup('pre-mods')
        self.manager.state['mods_trial'] = backup
        self.assertEqual(self.manager.boot_action(), 'recover_mods')
        (self.base / 'saves/world.db').write_bytes(b'interrupted')
        with patch.object(self.manager, 'start'):
            self.manager.execute('recover_mods', {})
        self.assertEqual((self.base / 'saves/world.db').read_bytes(), b'original world')
        self.assertNotIn('mods_trial', self.manager.state)

    def test_vanilla_cannot_install_and_does_not_publish_previous_bundle(self):
        self.upload()
        server.atomic_json(self.manager.active() / 'hearth.json', {'mode': 'vanilla', 'game': '1.0.16', 'mod': None})
        self.assertIsNone(self.manager.public_client_mods())
        self.assertFalse(self.manager.mods_view()['available'])
        with self.assertRaises(ValueError):
            self.manager.change_mods('mod_install', {'source': 'Team-Demo'})

    def test_generic_probe_requires_loader_even_when_game_ready(self):
        proc = MagicMock(); proc.stdout = iter(['Valheim version: 1.0.16', 'Game server connected']); proc.poll.return_value = None
        with patch.object(self.manager, 'spawn', return_value=proc), patch.object(self.manager, 'halt'):
            with self.assertRaisesRegex(RuntimeError, 'Тестовый мир'):
                self.manager.probe(self.base, None, None, mode='modded')

    def test_marker_write_failure_restarts_unchanged_server(self):
        proc = MagicMock(); proc.poll.return_value = None
        self.manager.proc = proc
        def stop(): self.manager.proc = None
        def start(): self.manager.proc = proc
        with patch.object(self.manager, 'stop', side_effect=stop), patch.object(self.manager, 'start', side_effect=start) as restart, patch.object(self.manager, 'save_state', side_effect=[OSError('disk full'), None]):
            with self.assertRaisesRegex(RuntimeError, 'Изменение модов отменено'):
                self.upload()
        restart.assert_called_once()
        self.assertTrue(self.manager.running())
        self.assertEqual(self.manager.mods.view()['packages'], [])
        self.assertNotIn('mods_trial', self.manager.state)

    def test_shutdown_after_staging_does_not_stop_game(self):
        self.manager.closing = True
        with patch.object(self.manager, 'stop') as stop:
            with self.assertRaisesRegex(ValueError, 'контейнер останавливается'):
                self.upload()
            stop.assert_not_called()

    def generic_install(self, probe_error=False):
        settings = self.manager.config.load()
        settings['server']['mode'] = 'modded'
        server.atomic_json(self.manager.config.path, settings)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as z:
            for name in ('BepInEx/core/BepInEx.dll', 'BepInEx/core/BepInEx.Preloader.dll', 'doorstop_libs/libdoorstop_x64.so', 'winhttp.dll', 'doorstop_config.ini'):
                z.writestr('BepInExPack_Valheim/' + name, b'loader fixture')
        metadata = {'latest': {'version_number': '5.4.2351', 'dependencies': [], 'download_url': 'https://thunderstore.io/package/download/denikson/BepInExPack_Valheim/5.4.2351/'}}
        process = MagicMock(); process.__enter__.return_value = process; process.stdout = []; process.wait.return_value = 0
        probe = patch.object(self.manager, 'probe', side_effect=RuntimeError('candidate rejected') if probe_error else None, return_value='1.0.16')
        with patch('mods._json', return_value=metadata), patch('mods._fetch', return_value=stream.getvalue()), patch('server.subprocess.Popen', return_value=process), probe, patch.object(self.manager, 'start'), patch.object(self.manager, 'wait_ready'):
            self.manager.install()

    def test_generic_loader_candidate_failure_preserves_live_cache(self):
        with self.assertRaisesRegex(RuntimeError, 'candidate rejected'):
            self.generic_install(probe_error=True)
        self.assertFalse(self.manager.mods.loader_info()['ready'])
        self.assertEqual(self.manager.state['active'], 'fixture')

    def test_generic_install_publishes_full_bundle_and_rollback_restores_cache(self):
        self.generic_install()
        self.assertEqual(self.manager.metadata()['mode'], 'modded')
        self.assertTrue(self.manager.mods.loader_info()['ready'])
        self.assertEqual(self.manager.public_client_mods()['kind'], 'full')
        with zipfile.ZipFile(self.base / 'client-mods.zip') as z:
            self.assertIn('winhttp.dll', z.namelist())
            self.assertNotIn('doorstop_libs/libdoorstop_x64.so', z.namelist())
        with patch.object(self.manager, 'start'):
            self.manager.restore(self.manager.state['rollback_backup'], rollback=True)
        self.assertEqual(self.manager.state['active'], 'fixture')
        self.assertFalse(self.manager.mods.loader_info()['ready'])
        self.assertIsNone(self.manager.public_client_mods())


class ModHttpTests(ModIntegrationTests):
    def setUp(self):
        super().setUp()
        self.manager.panel.save({**self.manager.panel.load(), 'auth': server.password_hash('correct-long-password')})
        class Handler(server.Handler):
            sessions = {}
            attempts = collections.deque(maxlen=100)
        Handler.manager = self.manager
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def tearDown(self):
        self.http.shutdown(); self.http.server_close()
        super().tearDown()

    def request(self, method, path, raw=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        conn.request(method, path, raw, headers or {})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def login(self):
        status, headers, raw = self.request('POST', '/api/login', json.dumps({'password': 'correct-long-password'}), {'X-Hearth': '1', 'Content-Type': 'application/json'})
        self.assertEqual(status, 200)
        return {'Cookie': headers['Set-Cookie'].split(';')[0], 'X-Hearth': '1', 'X-CSRF-Token': json.loads(raw)['csrf'], 'Content-Type': 'application/zip'}

    def test_upload_auth_csrf_and_size_boundary(self):
        self.assertEqual(self.request('GET', '/api/mods')[0], 401)
        self.assertEqual(self.request('POST', '/api/mods/upload', package(), {'Content-Type': 'application/zip'})[0], 403)
        headers = self.login()
        self.assertEqual(self.request('POST', '/api/mods/upload', b'', headers)[0], 400)
        headers['X-CSRF-Token'] = 'wrong'
        self.assertEqual(self.request('POST', '/api/mods/upload', package(), headers)[0], 403)

    def test_upload_transfers_lock_to_worker_and_public_download_is_exact(self):
        headers = self.login()
        status, _, _ = self.request('POST', '/api/mods/upload?name=Demo.zip&scope=both', package(), headers)
        self.assertEqual(status, 202)
        with self.manager.lock: pass
        self.assertFalse(self.manager.busy)
        self.assertEqual(self.manager.job['state'], 'done', self.manager.job)
        status, _, raw = self.request('GET', '/api/public')
        descriptor = json.loads(raw)['client_mods']
        self.assertEqual(status, 200)
        status, _, raw = self.request('GET', descriptor['url'])
        self.assertEqual(status, 200)
        self.assertEqual(len(raw), descriptor['size'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), descriptor['sha256'])
