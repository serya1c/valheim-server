import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import server


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.manager = server.Manager(self.base)

    def tearDown(self):
        for h in self.manager.log.handlers[:]:
            h.close()
            self.manager.log.removeHandler(h)
        self.tmp.cleanup()

    def test_zip_traversal_rejected(self):
        archive = self.base / 'bad.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('../escape', 'bad')
        with self.assertRaises(ValueError):
            server.safe_unzip(archive, self.base / 'out')
        self.assertFalse((self.base / 'escape').exists())

    def test_zip_symlink_rejected(self):
        archive = self.base / 'bad.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            i = zipfile.ZipInfo('link')
            i.external_attr = 0o120777 << 16
            z.writestr(i, '/etc/passwd')
        with self.assertRaises(ValueError):
            server.safe_unzip(archive, self.base / 'out')

    def test_player_tracking_and_sql_names(self):
        s = self.manager.store
        s.join("Odin'; DROP TABLE players;--")
        s.join("Odin'; DROP TABLE players;--")
        s.tick(["Odin'; DROP TABLE players;--"], 10)
        p = s.read()['players'][0]
        self.assertEqual(p['joins'], 2)
        self.assertEqual(p['seconds'], 10)

    def test_join_parser(self):
        line = '[Info : Unity Log] 09/24/2026 10:00:00: Got character ZDOID from Viking Name : 123:1'
        self.assertEqual(server.JOIN.search(line)[1], 'Viking Name')

    def test_linux_version_prefix(self):
        self.assertEqual(server.GAME_LOG_VERSION.search('Valheim version: l-1.0.15 (network version 40)')[1], '1.0.15')
        self.assertEqual(server.GAME_LOG_VERSION.search('Valheim version:1.0.15')[1], '1.0.15')

    def release(self, name):
        p = self.base / 'releases' / name
        p.mkdir()
        server.atomic_json(p / 'hearth.json', {'game': '1.0.15', 'mod': '0.10.2.0'})
        self.manager.state['active'] = name

    def test_consistent_backup_rejects_running_server(self):
        with patch.object(self.manager, 'running', return_value=True):
            with self.assertRaises(RuntimeError):
                self.manager.backup()

    def test_backup_restore_nested_world(self):
        self.release('one')
        world = self.base / 'saves/worlds_local/North'
        world.mkdir(parents=True)
        file = world / 'world.db'
        file.write_text('original')
        name = self.manager.backup()
        file.write_text('changed')
        with patch.object(self.manager, 'start'):
            self.manager.restore(name)
        self.assertEqual(file.read_text(), 'original')
        self.assertEqual(len(list((self.base / 'backups').glob('*-pre-restore.tar.gz'))), 1)

    def test_restore_rejects_other_release(self):
        self.release('one')
        name = self.manager.backup()
        self.release('two')
        with self.assertRaisesRegex(ValueError, 'другого релиза'):
            self.manager.restore(name)

    def test_rollback_restores_world_and_release(self):
        self.release('one')
        (self.base / 'saves/world.db').write_text('old world')
        backup = self.manager.backup('pre-update')
        self.release('two')
        self.manager.state['previous'] = 'one'
        (self.base / 'saves/world.db').write_text('new world')
        with patch.object(self.manager, 'start'):
            self.manager.restore(backup, rollback=True)
        self.assertEqual(self.manager.state['active'], 'one')
        self.assertEqual((self.base / 'saves/world.db').read_text(), 'old world')

    def test_restore_path_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.restore('../bad.tar.gz')

    def test_tar_traversal_rejected(self):
        with tarfile.open(self.base / 'backups/bad.tar.gz', 'w:gz') as tar:
            info = tarfile.TarInfo('../outside')
            info.size = 1
            tar.addfile(info, io.BytesIO(b'x'))
        with self.assertRaises(ValueError):
            self.manager.restore('bad.tar.gz')

    def test_rotation_preserves_manual_and_preupdate(self):
        for name in ['1-scheduled', '2-scheduled', '3-scheduled', '4-manual', '5-pre-update']:
            (self.base / 'backups' / (name + '.tar.gz')).touch()
        with patch.dict(os.environ, BACKUP_KEEP='2'):
            self.manager.prune_backups()
        self.assertEqual(len(list((self.base / 'backups').iterdir())), 4)
        self.assertTrue((self.base / 'backups/5-pre-update.tar.gz').exists())

    def test_operation_serialization(self):
        self.manager.lock.acquire()
        try:
            with self.assertRaises(ValueError):
                self.manager.submit('backup')
        finally:
            self.manager.lock.release()

    def test_password_redacted(self):
        with patch.dict(os.environ, SERVER_PASSWORD='secret123', PANEL_PASSWORD='panel123'):
            self.manager.say('secret123 and panel123')
        self.assertEqual(self.manager.tail[-1], '[REDACTED] and [REDACTED]')

    def test_failed_compatibility_never_stops_server(self):
        with patch('server.fetch', return_value={'tag_name':'0.10.2.0', 'body':'No compatibility information'}), patch.object(self.manager, 'stop') as stop:
            with self.assertRaises(ValueError):
                self.manager.install()
            stop.assert_not_called()

    def test_latest_release_discovers_future_versions(self):
        release = {'tag_name':'0.11.0.0', 'body':'# Patch Notes\nOld Valheim 1.0.15\n# Compatibility\nValheim 1.1.0\n# Install\nHelp'}
        with patch('server.fetch', return_value=release) as fetch:
            game, mod, _ = self.manager.latest_release()
        fetch.assert_called_once_with('https://api.github.com/repos/Grantapher/ValheimPlus/releases/latest')
        self.assertEqual((game, mod), ('1.1.0', '0.11.0.0'))

    def test_latest_release_rejects_unsafe_or_ambiguous_metadata(self):
        for overrides in [{'draft':True}, {'prerelease':True}, {'tag_name':'../../bad'}, {'body':None}, {'body':'Valheim 1.0.15 and Valheim 1.1.0'}]:
            with self.subTest(overrides=overrides):
                release = {'tag_name':'0.10.2.0', 'body':'Valheim 1.0.15', **overrides}
                with patch('server.fetch', return_value=release), patch.object(self.manager, 'stop') as stop:
                    with self.assertRaises(ValueError):
                        self.manager.install()
                    stop.assert_not_called()

    def test_install_action_ignores_legacy_version_fields(self):
        with patch.object(self.manager, 'install') as install:
            self.manager.execute('install', {'game':'0.0.1', 'mod':'0.0.1'})
        install.assert_called_once_with()

    def test_missing_latest_asset_preserves_server(self):
        with patch('server.fetch', return_value={'tag_name':'0.11.0.0', 'body':'Valheim 1.1.0', 'assets':[]}), patch.object(self.manager, 'stop') as stop:
            with self.assertRaisesRegex(ValueError, 'UnixServer.zip'):
                self.manager.install()
            stop.assert_not_called()

    def test_backup_failure_restarts_previously_running_server(self):
        with patch.object(self.manager, 'running', return_value=True), patch.object(self.manager, 'stop'), patch.object(self.manager, 'backup', side_effect=OSError('disk full')), patch.object(self.manager, 'start') as start:
            with self.assertRaises(OSError):
                self.manager.execute('backup', {})
            start.assert_called_once()

    def install_fixture(self):
        archive = self.base / 'fixture.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('BepInEx/plugins/ValheimPlus.dll', 'fixture')
        blob = archive.read_bytes()
        release = {'tag_name': '0.10.2.0', 'body': 'Valheim 1.0.15 (n-40)', 'assets': [{'name': 'UnixServer.zip',
                   'browser_download_url': 'https://github.com/Grantapher/ValheimPlus/releases/download/0.10.2.0/UnixServer.zip'}]}
        def fetch(url, target=None):
            if target:
                target.write_bytes(blob)
            else:
                return release
        process = MagicMock()
        process.__enter__.return_value = process
        process.stdout = ['Steam fixture\n']
        process.wait.return_value = 0
        return fetch, process, hashlib.sha256(blob).hexdigest()

    def test_failed_candidate_preserves_active_release(self):
        self.release('old')
        fetch, process, digest = self.install_fixture()
        with patch('server.fetch', side_effect=fetch), patch('server.subprocess.Popen', return_value=process), patch('server.PINNED_SHA', digest), patch.object(self.manager, 'probe', side_effect=RuntimeError('wrong game version')), patch.object(self.manager, 'stop') as stop:
            with self.assertRaisesRegex(RuntimeError, 'wrong game version'):
                self.manager.install()
            stop.assert_not_called()
        self.assertEqual(self.manager.state['active'], 'old')
        self.assertEqual([p.name for p in (self.base / 'releases').iterdir()], ['old'])

    def test_successful_update_preserves_rollback_point(self):
        self.release('old')
        (self.base / 'saves/world.db').write_text('world before update')
        fetch, process, digest = self.install_fixture()
        with patch('server.fetch', side_effect=fetch), patch('server.subprocess.Popen', return_value=process), patch('server.PINNED_SHA', digest), patch.object(self.manager, 'probe'), patch.object(self.manager, 'start') as start:
            self.manager.install()
            start.assert_called_once()
        self.assertEqual(self.manager.state['previous'], 'old')
        self.assertNotEqual(self.manager.state['active'], 'old')
        self.assertTrue((self.base / 'backups' / self.manager.state['rollback_backup']).is_file())
        self.assertEqual(self.manager.metadata()['mod'], '0.10.2.0')

    def test_hash_failure_never_reaches_probe(self):
        self.release('old')
        fetch, process, _ = self.install_fixture()
        with patch('server.fetch', side_effect=fetch), patch('server.subprocess.Popen', return_value=process), patch.object(self.manager, 'probe') as probe:
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                self.manager.install()
            probe.assert_not_called()
        self.assertEqual(self.manager.state['active'], 'old')


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        server.Handler.manager = server.Manager(Path(cls.tmp.name))
        server.Handler.password = 'correct-long-password'
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        for h in server.Handler.manager.log.handlers:
            h.close()
        cls.tmp.cleanup()

    def setUp(self):
        server.Handler.attempts.clear()
        server.Handler.sessions.clear()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port)
        conn.request(method, path, json.dumps(body) if body is not None else None, headers or {})
        r = conn.getresponse()
        raw = r.read()
        result = (r.status, dict(r.getheaders()), raw)
        conn.close()
        return result

    def login(self):
        s, h, b = self.request('POST', '/api/login', {'password':'correct-long-password'}, {'Content-Type':'application/json','X-Hearth':'1'})
        self.assertEqual(s, 200)
        return {'Cookie': h['Set-Cookie'].split(';')[0], 'Content-Type':'application/json', 'X-Hearth':'1', 'X-CSRF-Token':json.loads(b)['csrf']}

    def test_auth_required(self):
        self.assertEqual(self.request('GET', '/api/status')[0], 401)
        self.assertEqual(self.request('GET', '/api/config')[0], 401)
        self.assertEqual(self.request('GET', '/api/backup/test.tar.gz')[0], 401)

    def test_landing_and_admin_routes(self):
        for path, marker in [('/', 'Твоя сага'), ('/admin', 'login-form'), ('/admin/', 'login-form')]:
            status, headers, raw = self.request('GET', path)
            self.assertEqual(status, 200)
            self.assertIn(marker, raw.decode('utf-8-sig'))
        for path in ['/landing.js','/landing.css','/north.svg']:
            self.assertEqual(self.request('GET', path)[0], 200)

    def test_public_api_exposes_only_approved_fields(self):
        with patch.object(server.Handler.manager, 'metadata', return_value={'game':'1.0.15','mod':'0.10.2.0','secret':'must-not-leak'}):
            status, _, raw = self.request('GET','/api/public')
        data = json.loads(raw)
        self.assertEqual(status,200)
        self.assertEqual(set(data), {'title','description','address','community_url','running','players','game','mod','server_name'})
        self.assertNotIn('must-not-leak', raw.decode())
        self.assertNotIn('password',raw.decode())

    def test_public_installer_download_matches_published_hash(self):
        status, headers, raw = self.request('GET', '/downloads/Loki-Mod-Installer.exe')
        self.assertEqual(status, 200)
        self.assertTrue(raw.startswith(b'MZ'))
        self.assertEqual(int(headers['Content-Length']), len(raw))
        self.assertEqual(headers['Content-Disposition'], 'attachment; filename="Loki-Mod-Installer.exe"')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        digest = self.request('GET', '/downloads/Loki-Mod-Installer.exe.sha256')[2].decode().split()[0]
        self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
        self.assertIn(b'href="/downloads/Loki-Mod-Installer.exe"', self.request('GET', '/')[2])

    def test_download_route_does_not_expose_arbitrary_files(self):
        for path in ['/downloads/../server.py', '/downloads/server.py', '/downloads/%2e%2e/server.py']:
            self.assertNotEqual(self.request('GET', path)[0], 200)

    def test_public_online_does_not_expose_names_or_stale_counts(self):
        manager = server.Handler.manager
        with patch.object(manager,'running',return_value=True), patch.object(manager,'online',{'count':2,'names':['private-player'],'at':time.time()}):
            _, _, raw = self.request('GET','/api/public')
            self.assertEqual(json.loads(raw)['players'],2)
            self.assertNotIn('private-player',raw.decode())
        with patch.object(manager,'running',return_value=True), patch.object(manager,'online',{'count':2,'at':time.time()-60}):
            self.assertIsNone(json.loads(self.request('GET','/api/public')[2])['players'])

    def test_health(self):
        self.assertEqual(self.request('GET', '/health')[0], 200)

    def test_search_metadata_and_routes(self):
        status, _, raw = self.request('GET','/?utm_source=discord')
        self.assertEqual(status,200)
        self.assertIn(b'rel="canonical" href="https://loki.ach-play.ru/"',raw)
        self.assertIn(b'loki.ach-play.ru:2456',raw)
        self.assertNotIn(b'{{',raw)
        self.assertIn(b'Sitemap: https://loki.ach-play.ru/sitemap.xml',self.request('GET','/robots.txt')[2])
        self.assertIn(b'<loc>https://loki.ach-play.ru/</loc>',self.request('GET','/sitemap.xml')[2])
        self.assertEqual(self.request('GET','/admin')[1]['X-Robots-Tag'],'noindex, nofollow')

    def test_search_html_escapes_configured_text(self):
        config=server.Handler.manager.config
        settings=config.load()
        settings['landing']['title']='Loki <script>alert(1)</script>'
        settings['landing']['description']='" onload="bad'
        with patch.object(config,'load',return_value=settings):
            status, _, raw = self.request('GET','/')
        self.assertEqual(status,200)
        self.assertNotIn(b'<script>alert(1)</script>',raw)
        self.assertIn(b'&lt;script&gt;',raw)
        self.assertIn(b'&quot; onload=&quot;bad',raw)

    def test_no_simple_cross_site_login(self):
        self.assertEqual(self.request('POST', '/api/login', {'password':'correct-long-password'})[0], 403)

    def test_status_and_security_headers(self):
        headers = self.login()
        s, h, b = self.request('GET', '/api/status', headers=headers)
        self.assertEqual(s, 200)
        self.assertEqual(h['X-Frame-Options'], 'DENY')
        self.assertNotIn('correct-long-password', b.decode())

    def test_csrf_required(self):
        headers = self.login()
        headers.pop('X-CSRF-Token')
        self.assertEqual(self.request('POST', '/api/action', {'action':'stop'}, headers)[0], 403)

    def test_logout_invalidates_cookie(self):
        headers = self.login()
        self.assertEqual(self.request('POST', '/api/logout', {}, headers)[0], 200)
        self.assertEqual(self.request('GET', '/api/status', headers=headers)[0], 401)

    def test_rate_limit(self):
        headers = {'Content-Type':'application/json','X-Hearth':'1'}
        for _ in range(10):
            self.assertEqual(self.request('POST', '/api/login', {'password':'wrong'}, headers)[0], 401)
        self.assertEqual(self.request('POST', '/api/login', {'password':'wrong'}, headers)[0], 429)

    def test_unknown_action(self):
        self.assertEqual(self.request('POST', '/api/action', {'action':'shell'}, self.login())[0], 400)

    def test_json_array_rejected(self):
        self.assertEqual(self.request('POST', '/api/action', [], self.login())[0], 400)

    def test_authenticated_download_traversal(self):
        self.assertEqual(self.request('GET', '/api/backup/../../etc/passwd', headers=self.login())[0], 400)


if __name__ == '__main__':
    unittest.main(verbosity=2)
