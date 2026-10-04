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
        self.manager.panel.save({**self.manager.panel.load(), 'auth':server.password_hash('testing-panel-password'), 'backup_keep':2})
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
        with patch('server.fetch', side_effect=fetch), patch('server.subprocess.Popen', return_value=process), patch('server.PINNED_SHA', digest), patch.object(self.manager, 'probe'), patch.object(self.manager, 'wait_ready'), patch.object(self.manager, 'start') as start:
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

    def test_restart_during_trial_selects_rollback(self):
        manager = MagicMock()
        manager.state = {'active': 'new', 'previous': 'old', 'update_trial': True}
        manager.boot_action.return_value = 'rollback'
        with patch.dict(os.environ, {'PANEL_PASSWORD': 'test-panel-password', 'SERVER_PASSWORD': 'test-game-password', 'WORLD_NAME': 'North'}), patch('server.Manager', return_value=manager), patch('server.ThreadingHTTPServer'), patch('server.threading.Thread'), patch('server.signal.signal'), patch('server.os.umask'):
            server.main()
        manager.submit.assert_called_once_with('rollback')

    def test_vanilla_install_skips_github_and_can_rollback_to_plus(self):
        self.release('old')
        settings=self.manager.config.load();settings['server']['mode']='vanilla'
        server.atomic_json(self.manager.config.path,settings)
        _, process, _=self.install_fixture()
        with patch('server.fetch') as fetch, patch('server.subprocess.Popen',return_value=process), patch.object(self.manager,'probe',return_value='1.0.16') as probe, patch.object(self.manager,'start'), patch.object(self.manager,'wait_ready') as ready:
            self.manager.install()
        fetch.assert_not_called()
        self.assertEqual(probe.call_args.args[1:],(None,None))
        ready.assert_called_once_with('1.0.16',None)
        self.assertEqual(self.manager.metadata()['mode'],'vanilla')
        self.assertIsNone(self.manager.metadata()['mod'])
        self.assertFalse((self.manager.active()/'BepInEx').exists())
        with patch.object(self.manager,'start'):
            self.manager.execute('rollback',{})
        self.assertEqual(self.manager.state['active'],'old')
        self.assertEqual(self.manager.metadata()['mod'],'0.10.2.0')

    def test_vanilla_spawn_has_no_loader_even_with_inherited_environment(self):
        self.release('plain')
        server.atomic_json(self.manager.active()/'hearth.json',{'mode':'vanilla','game':'1.0.16','mod':None})
        (self.manager.active()/'valheim_server.x86_64').touch()
        with patch.dict(os.environ,LD_PRELOAD='unexpected.so',DOORSTOP_ENABLED='1'), patch('server.subprocess.Popen') as spawn:
            self.manager.spawn(self.manager.active(),self.base/'saves',2466)
        env=spawn.call_args.kwargs['env']
        self.assertNotIn('LD_PRELOAD',env)
        self.assertNotIn('DOORSTOP_ENABLED',env)
        self.assertIn('2466',spawn.call_args.args[0])

    def test_vanilla_probe_accepts_game_ready_without_mod(self):
        process=MagicMock(stdout=io.StringIO('Valheim version: l-1.0.16\nGame server connected\n'))
        process.poll.return_value=None
        with patch.object(self.manager,'spawn',return_value=process), patch.object(self.manager,'halt'):
            self.assertEqual(self.manager.probe(self.base,None,None),'1.0.16')

    def pending(self, digest):
        return {'token': 'test-approval', 'declared': '1.0.15', 'actual': '1.0.16',
                'mod': '0.10.2.0', 'sha256': digest, 'expires': time.time() + 1800}

    def test_mismatch_requests_approval_without_stopping_server(self):
        self.release('old')
        fetch, process, digest = self.install_fixture()
        with patch('server.fetch', side_effect=fetch), patch('server.subprocess.Popen', return_value=process), patch('server.PINNED_SHA', digest), patch.object(self.manager, 'probe', side_effect=server.CompatibilityApprovalRequired('1.0.16')), patch.object(self.manager, 'stop') as stop:
            with self.assertRaisesRegex(RuntimeError, 'Одобрите'):
                self.manager.install()
            stop.assert_not_called()
        self.assertEqual(self.manager.compatibility['actual'], '1.0.16')
        self.assertEqual(self.manager.compatibility['sha256'], digest)
        self.assertEqual(self.manager.state['active'], 'old')
        self.assertEqual([p.name for p in (self.base / 'releases').iterdir()], ['old'])

    def test_approved_update_records_actual_version_and_consumes_approval(self):
        self.release('old')
        fetch, process, digest = self.install_fixture()
        self.manager.compatibility = self.pending(digest)
        with patch('server.fetch', side_effect=fetch), patch('server.subprocess.Popen', return_value=process), patch('server.PINNED_SHA', digest), patch.object(self.manager, 'probe') as probe, patch.object(self.manager, 'start'), patch.object(self.manager, 'wait_ready') as ready:
            self.manager.execute('install', {'approval_token': 'test-approval'})
        self.assertEqual(probe.call_args.args[1:], ('1.0.16', '0.10.2.0'))
        ready.assert_called_once_with('1.0.16', '0.10.2.0')
        self.assertEqual(self.manager.metadata()['game'], '1.0.16')
        self.assertTrue(self.manager.metadata()['compatibility']['approved'])
        self.assertFalse(self.manager.state['update_trial'])
        self.assertIsNone(self.manager.compatibility)
        with self.assertRaises(ValueError):
            self.manager.install('test-approval')

    def test_invalid_or_expired_approval_does_not_download(self):
        for token, expires in [('wrong', time.time()+60), ('test-approval', 0), (True, time.time()+60)]:
            self.manager.compatibility = self.pending('digest')
            self.manager.compatibility['expires'] = expires
            with patch('server.fetch') as fetch, self.assertRaises(ValueError):
                self.manager.install(token)
            fetch.assert_not_called()

    def test_changed_archive_requires_new_approval(self):
        self.release('old')
        fetch, process, digest = self.install_fixture()
        self.manager.compatibility = self.pending('different-digest')
        with patch('server.fetch', side_effect=fetch), patch('server.subprocess.Popen', return_value=process), patch('server.PINNED_SHA', digest), patch.object(self.manager, 'stop') as stop:
            with self.assertRaisesRegex(ValueError, 'Состав обновления'):
                self.manager.install('test-approval')
            stop.assert_not_called()
        self.assertEqual(self.manager.state['active'], 'old')

    def test_approved_update_still_checks_hash(self):
        fetch, process, digest = self.install_fixture()
        self.manager.compatibility = self.pending(digest)
        with patch('server.fetch', side_effect=fetch), patch('server.subprocess.Popen', return_value=process), patch.object(self.manager, 'probe') as probe:
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                self.manager.install('test-approval')
            probe.assert_not_called()

    def test_failed_world_start_restores_old_release_world_and_config(self):
        self.release('old')
        world = self.base / 'saves/world.db'
        config = self.base / 'config/valheim_plus.cfg'
        world.write_text('original world')
        config.write_text('original config')
        fetch, process, digest = self.install_fixture()
        def failed_start(*args):
            world.write_text('converted world')
            config.write_text('changed config')
            raise RuntimeError('world failed')
        with patch('server.fetch', side_effect=fetch), patch('server.subprocess.Popen', return_value=process), patch('server.PINNED_SHA', digest), patch.object(self.manager, 'probe'), patch.object(self.manager, 'start'), patch.object(self.manager, 'wait_ready', side_effect=failed_start):
            with self.assertRaisesRegex(RuntimeError, 'автоматический откат'):
                self.manager.install()
        self.assertEqual(self.manager.state['active'], 'old')
        self.assertFalse(self.manager.state['update_trial'])
        self.assertEqual(world.read_text(), 'original world')
        self.assertEqual(config.read_text(), 'original config')
        self.assertEqual(json.loads((self.base / 'state.json').read_text())['active'], 'old')
        backups = list((self.base / 'backups').glob('*-pre-restore.tar.gz'))
        self.assertEqual(len(backups), 1)
        with tarfile.open(backups[0]) as archive:
            self.assertEqual(archive.extractfile('saves/world.db').read(), b'converted world')

    def test_probe_requires_ready_correct_mod_and_no_errors(self):
        lines = 'Valheim version: l-1.0.16\nBepInEx 5.4.23\nLoading [Valheim Plus 0.10.2.0]\n'
        for output, expected in [(lines, RuntimeError), (lines+'Game server connected\n', server.CompatibilityApprovalRequired), (lines+'HarmonyException: bad patch\nGame server connected\n', RuntimeError), (lines.replace('0.10.2.0', '0.10.1.0')+'Game server connected\n', RuntimeError)]:
            process = MagicMock(stdout=io.StringIO(output))
            process.poll.return_value = None
            with patch.object(self.manager, 'spawn', return_value=process), patch.object(self.manager, 'halt'):
                with self.assertRaises(expected) as caught:
                    self.manager.probe(self.base, '1.0.15', '0.10.2.0')
                if expected is RuntimeError:
                    self.assertNotIsInstance(caught.exception, server.CompatibilityApprovalRequired)

    def test_world_readiness_rejects_exit_errors_and_timeout(self):
        with patch.object(self.manager, 'running', return_value=False), self.assertRaises(RuntimeError):
            self.manager.wait_ready('1.0.16', '0.10.2.0')
        self.manager.startup = {'error': 'MissingMethodException'}
        with patch.object(self.manager, 'running', return_value=True), self.assertRaises(RuntimeError):
            self.manager.wait_ready('1.0.16', '0.10.2.0')
        with self.assertRaisesRegex(RuntimeError, 'готовность'):
            self.manager.wait_ready('1.0.16', '0.10.2.0', timeout=0)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        server.Handler.manager = server.Manager(Path(cls.tmp.name))
        server.Handler.password = 'correct-long-password'
        server.Handler.manager.panel.save({**server.Handler.manager.panel.load(),'auth':server.password_hash('correct-long-password')})
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

    def test_operations_requires_auth_csrf_and_hides_webhook(self):
        body={'command':'discord','url':'https://discord.com/api/webhooks/123/'+'a'*40,'events':[]}
        headers={'Content-Type':'application/json','X-Hearth':'1'}
        self.assertEqual(self.request('POST','/api/operations',body,headers)[0],403)
        headers=self.login();bad=dict(headers);bad['X-CSRF-Token']='wrong'
        self.assertEqual(self.request('POST','/api/operations',body,bad)[0],403)
        status,_,raw=self.request('POST','/api/operations',body,headers)
        self.assertEqual(status,200);self.assertNotIn(body['url'].encode(),raw)
        self.assertNotIn(body['url'].encode(),self.request('GET','/api/status',headers=headers)[2])
        public=json.loads(self.request('GET','/api/public')[2]);self.assertNotIn('discord',public)
        self.request('POST','/api/operations',{'command':'discord','remove':True,'events':[]},headers)

    def test_landing_and_admin_routes(self):
        for path, marker in [('/', 'Твоя сага'), ('/admin', 'login-form'), ('/admin/', 'login-form')]:
            status, headers, raw = self.request('GET', path)
            self.assertEqual(status, 200)
            self.assertIn(marker, raw.decode('utf-8-sig'))
        for path in ['/landing.js','/landing.css','/north.svg']:
            self.assertEqual(self.request('GET', path)[0], 200)

    def test_custom_domain_and_vanilla_public_page(self):
        data=self.http.RequestHandlerClass.manager.config.load()
        data['landing'].update(site_url='https://north.example.org',title='North',address='north.example.org:2466',community_url='')
        data['server']['mode']='vanilla'
        manager=self.http.RequestHandlerClass.manager
        with patch.object(manager.config,'load',return_value=data),patch.object(manager,'metadata',return_value={'game':'1.0.16','mod':None,'mode':'vanilla'}):
            page=self.request('GET','/')[2].decode()
            self.assertIn('rel="canonical" href="https://north.example.org/"',page)
            self.assertIn('Ванильный сервер',page)
            self.assertIn('<article data-plus hidden>',page)
            self.assertNotIn('loki.ach-play.ru',page)
            self.assertIn('https://north.example.org/sitemap.xml',self.request('GET','/robots.txt')[2].decode())
            self.assertIn('<loc>https://north.example.org/</loc>',self.request('GET','/sitemap.xml')[2].decode())
            self.assertEqual(json.loads(self.request('GET','/api/public')[2])['mode'],'vanilla')
        with patch.object(manager.config,'load',return_value=data),patch.object(manager,'metadata',return_value={'game':'1.0.15','mod':'0.10.2.0'}):
            self.assertEqual(json.loads(self.request('GET','/api/public')[2])['mode'],'plus')

    def test_public_api_exposes_only_approved_fields(self):
        with patch.object(server.Handler.manager, 'metadata', return_value={'game':'1.0.15','mod':'0.10.2.0','secret':'must-not-leak'}):
            status, _, raw = self.request('GET','/api/public')
        data = json.loads(raw)
        self.assertEqual(status,200)
        self.assertEqual(set(data), {'title','description','description_en','address','community_url','running','players','game','mod','server_name','mode','site_url','public_listing','maintenance'})
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

    def test_linux_installer_download_and_instructions(self):
        status, headers, raw = self.request('GET', '/downloads/Loki-Mod-Installer-Linux.sh')
        self.assertEqual(status, 200)
        self.assertTrue(raw.startswith(b'#!/bin/sh\n'))
        self.assertNotIn(b'\r', raw)
        self.assertIn('attachment;', headers['Content-Disposition'])
        digest = self.request('GET', '/downloads/Loki-Mod-Installer-Linux.sh.sha256')[2].decode().split()[0]
        self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
        html = self.request('GET', '/')[2]
        self.assertIn(b'href="/downloads/Loki-Mod-Installer-Linux.sh"', html)
        self.assertIn(b'WINEDLLOVERRIDES="winhttp=n,b" %command%', html)

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
