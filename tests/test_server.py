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
        self.build_check = patch.object(self.manager, 'latest_steam_build', return_value='1000')
        self.build_check.start()
        self.addCleanup(self.build_check.stop)
        self.probe_stability = patch('server.PROBE_STABLE_SECONDS', 0)
        self.probe_stability.start()
        self.addCleanup(self.probe_stability.stop)

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

    def test_backup_removes_temporary_kicks_and_preserves_permanent_bans(self):
        self.release('one')
        steam_id = '76561198000000001'
        permanent = 'Steam_76561198000000002'
        banned = self.base / 'saves/bannedlist.txt'
        banned.write_text('// Server rules\n' + permanent + '\n', encoding='utf-8')
        with patch.object(self.manager, 'running', return_value=True):
            self.manager.player_access.perform('kick', steam_id)
        name = self.manager.backup()
        with tarfile.open(self.base / 'backups' / name, 'r:gz') as archive:
            saved = archive.extractfile('saves/bannedlist.txt').read().decode('utf-8')
        self.assertEqual(saved.splitlines(), ['// Server rules', permanent])
        self.assertEqual(banned.read_bytes().decode('utf-8'), saved)
        with patch.object(self.manager, 'start'):
            self.manager.restore(name)
        self.assertEqual(self.manager.player_access.view()['kicks'], [])
        self.assertEqual(self.manager.player_access.view()['banned'], ['76561198000000002'])

    def test_poll_expires_kick_while_busy_operation_holds_manager_lock(self):
        steam_id = '76561198000000001'
        self.manager.panel.save({**self.manager.panel.load(), 'backup_hours': 0})
        with patch.object(self.manager, 'running', return_value=True), patch('server.time.time', return_value=1000):
            self.manager.player_access.perform('kick', steam_id)
        self.manager.busy = True
        errors = []

        def poll_once():
            try:
                self.manager.poll()
            except BaseException as error:
                errors.append(error)

        def end_cycle(_):
            self.manager.closing = True

        self.manager.lock.acquire()
        try:
            with patch.object(self.manager, 'running', return_value=False), patch('server.time.time', return_value=1031), patch('server.time.sleep', side_effect=end_cycle), patch.object(self.manager.operations, 'tick'), patch.object(self.manager, 'submit') as submit:
                worker = threading.Thread(target=poll_once, daemon=True)
                worker.start()
                worker.join(timeout=5)
                blocked = worker.is_alive()
                submit.assert_not_called()
        finally:
            self.manager.closing = True
            self.manager.lock.release()
            worker.join(timeout=5)
        self.assertFalse(blocked, 'Expiration must finish while the long operation still holds its lock')
        self.assertEqual(errors, [])
        self.assertEqual(self.manager.player_access.view()['kicks'], [])
        self.assertEqual(self.manager.player_access.view()['banned'], [])
        self.assertNotIn('Steam_' + steam_id, (self.base / 'saves/bannedlist.txt').read_text(encoding='utf-8').splitlines())

    def test_historical_backup_with_temporary_kick_is_cleaned_before_start(self):
        self.release('one')
        steam_id = '76561198000000001'
        permanent = 'Steam_76561198000000002'
        contents = ('// Server rules\n' + permanent + '\n'
                    '// Hearth temporary kick Steam_' + steam_id + ' until 4000000000\n'
                    'Steam_' + steam_id + '\n').encode('utf-8')
        fixture = self.base / 'backups/historical.tar.gz'
        with tarfile.open(fixture, 'w:gz') as archive:
            for folder in ('saves', 'config'):
                entry = tarfile.TarInfo(folder)
                entry.type = tarfile.DIRTYPE
                archive.addfile(entry)
            for name, data in [('saves/bannedlist.txt', contents), ('manifest.json', json.dumps({'release': 'one'}).encode())]:
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
        process = MagicMock()
        process.poll.return_value = 0

        def launch(*_):
            self.assertEqual((self.base / 'saves/bannedlist.txt').read_text(encoding='utf-8').splitlines(), ['// Server rules', permanent])
            return process

        with patch.object(self.manager, 'metadata', return_value={'mode': 'vanilla'}), patch.object(self.manager, 'spawn', side_effect=launch) as spawn, patch('server.threading.Thread'):
            self.manager.restore(fixture.name)
        spawn.assert_called_once()
        self.assertEqual(self.manager.player_access.view()['kicks'], [])
        self.assertEqual(self.manager.player_access.view()['banned'], ['76561198000000002'])
        self.assertEqual((self.base / 'saves/bannedlist.txt').read_text(encoding='utf-8').splitlines(), ['// Server rules', permanent])

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

    def test_missing_latest_asset_never_stops_server(self):
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
        for overrides in [{'draft':True}, {'prerelease':True}, {'tag_name':'../../bad'}]:
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
        def downloaded():
            for stage in (self.base / 'releases').iterdir():
                if not (stage / 'hearth.json').exists():
                    (stage / 'steamapps').mkdir(exist_ok=True)
                    (stage / 'steamapps/appmanifest_896660.acf').write_text('"AppState" { "appid" "896660" "StateFlags" "4" "buildid" "1000" }')
                    (stage / 'valheim_server.x86_64').touch()
            return process
        process.__enter__.side_effect = downloaded
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
        with patch('server.fetch', side_effect=fetch), patch('server.subprocess.Popen', return_value=process), patch('server.PINNED_SHA', digest), patch.object(self.manager, 'probe', return_value='1.0.15'), patch.object(self.manager, 'wait_ready'), patch.object(self.manager, 'start') as start:
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
        process.returncode=0
        with patch.object(self.manager,'spawn',return_value=process), patch.object(self.manager,'halt'):
            self.assertEqual(self.manager.probe(self.base,None,None),'1.0.16')

    def test_healthy_mismatch_is_automatically_approved_without_second_download(self):
        self.release('old')
        fetch, process, digest = self.install_fixture()
        with patch('server.fetch', side_effect=fetch) as download, patch('server.subprocess.Popen', return_value=process) as steam, patch('server.PINNED_SHA', digest), patch.object(self.manager, 'probe', return_value='1.0.16') as probe, patch.object(self.manager, 'start'), patch.object(self.manager, 'wait_ready') as ready:
            result = self.manager.execute('install', {})
        self.assertTrue(result['updated'])
        self.assertEqual(probe.call_args.args[1:], ('1.0.15', '0.10.2.0'))
        ready.assert_called_once_with('1.0.16', '0.10.2.0')
        steam.assert_called_once()
        self.assertEqual(sum(call.args[1:] != () for call in download.call_args_list), 1)
        self.assertEqual(self.manager.metadata()['game'], '1.0.16')
        self.assertEqual(self.manager.metadata()['steam_build'], '1000')
        self.assertTrue(self.manager.metadata()['compatibility']['approved'])
        self.assertTrue(self.manager.metadata()['compatibility']['automatic'])
        self.assertFalse(self.manager.state['update_trial'])

    def test_automatic_approval_never_bypasses_archive_hash(self):
        fetch, process, digest = self.install_fixture()
        with patch('server.fetch', side_effect=fetch), patch('server.subprocess.Popen', return_value=process), patch.object(self.manager, 'probe') as probe:
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                self.manager.install()
            probe.assert_not_called()

    def up_to_date_release(self, digest=None, mode='plus', build='1000', manifest=False):
        folder = self.base / 'releases/old'
        folder.mkdir(exist_ok=True)
        self.manager.state.update(active='old', previous='rollback-point')
        metadata = {'game': '1.0.16', 'mode': mode, 'steam_build': build,
                    'mod': '0.10.2.0' if mode == 'plus' else None, 'mod_sha256': digest}
        server.atomic_json(folder / 'hearth.json', metadata)
        (folder / 'valheim_server.x86_64').write_bytes(b'game fixture')
        if manifest:
            metadata.pop('steam_build')
            server.atomic_json(folder / 'hearth.json', metadata)
            (folder / 'steamapps').mkdir(exist_ok=True)
            (folder / 'steamapps/appmanifest_896660.acf').write_text('"AppState" { "appid" "896660" "StateFlags" "4" "buildid" "'+build+'" }')
        return folder

    def test_identical_plus_skips_download_probe_backup_restart_and_client_publish(self):
        fetch, _, digest = self.install_fixture()
        folder = self.up_to_date_release(digest)
        original_metadata = (folder / 'hearth.json').read_bytes()
        original_state = dict(self.manager.state)
        with patch('server.fetch', side_effect=fetch) as metadata, patch('server.subprocess.Popen') as download, patch('server.PINNED_SHA', digest), patch.object(self.manager, 'probe') as probe, patch.object(self.manager, 'stop') as stop, patch.object(self.manager, 'backup') as backup, patch.object(self.manager, 'start') as start, patch.object(self.manager, 'publish_client_mods') as publish, patch.object(self.manager.operations, 'notify') as notify:
            result = self.manager.execute('install', {})
        self.assertFalse(result['updated'])
        self.assertIn('Обновлений нет', result['message'])
        metadata.assert_called_once()
        for operation in (download, probe, stop, backup, start, publish, notify):
            operation.assert_not_called()
        self.assertEqual(self.manager.state, original_state)
        self.assertEqual((folder / 'hearth.json').read_bytes(), original_metadata)
        self.assertEqual(list((self.base / 'backups').iterdir()), [])
        self.assertEqual(list((self.base / 'releases').iterdir()), [folder])

    def test_identical_vanilla_and_modded_skip_even_candidate_creation(self):
        for mode in ('vanilla', 'modded'):
            with self.subTest(mode=mode):
                settings = self.manager.config.load(); settings['server']['mode'] = mode
                server.atomic_json(self.manager.config.path, settings)
                self.up_to_date_release(mode=mode)
                with patch.object(self.manager.mods, 'latest_loader_version', return_value='5.4.2351'), patch.object(self.manager.mods, 'loader_info', return_value={'version':'5.4.2351'}), patch('server.fetch') as fetch, patch('server.subprocess.Popen') as download, patch.object(self.manager, 'stop') as stop:
                    result = self.manager.install()
                self.assertFalse(result['updated'])
                fetch.assert_not_called(); download.assert_not_called(); stop.assert_not_called()

    def test_changed_loader_version_updates_modded_even_when_steam_is_unchanged(self):
        settings = self.manager.config.load(); settings['server']['mode'] = 'modded'
        server.atomic_json(self.manager.config.path, settings)
        self.up_to_date_release(mode='modded')
        with patch.object(self.manager.mods, 'latest_loader_version', return_value='5.4.2352'), patch.object(self.manager.mods, 'loader_info', return_value={'version':'5.4.2351'}), patch('server.subprocess.Popen', side_effect=RuntimeError('download started')) as download, patch.object(self.manager, 'stop') as stop:
            with self.assertRaisesRegex(RuntimeError, 'download started'):
                self.manager.install()
            download.assert_called_once(); stop.assert_not_called()

    def test_legacy_metadata_uses_installed_manifest_and_invalid_manifest_cannot_skip(self):
        fetch, process, digest = self.install_fixture()
        folder = self.up_to_date_release(digest, manifest=True)
        with patch('server.fetch', side_effect=fetch), patch('server.PINNED_SHA', digest), patch('server.subprocess.Popen') as download:
            self.assertFalse(self.manager.install()['updated'])
            download.assert_not_called()
        (folder / 'steamapps/appmanifest_896660.acf').write_text('"AppState" { "appid" "896660" "StateFlags" "6" "buildid" "1000" }')
        metadata = self.manager.metadata(); metadata['steam_build'] = '1000'
        server.atomic_json(folder / 'hearth.json', metadata)
        with patch('server.fetch', side_effect=fetch), patch('server.PINNED_SHA', digest), patch('server.subprocess.Popen', return_value=process) as download, patch.object(self.manager, 'probe', side_effect=RuntimeError('candidate checked')):
            with self.assertRaisesRegex(RuntimeError, 'candidate checked'):
                self.manager.install()
            download.assert_called_once()

    def test_changed_build_digest_or_mode_does_not_skip_candidate(self):
        for build, digest_changed, current_mode in [('999', False, 'plus'), ('1000', True, 'plus'), ('1000', False, 'vanilla')]:
            with self.subTest(build=build, digest=digest_changed, mode=current_mode):
                fetch, process, digest = self.install_fixture()
                self.up_to_date_release('0'*64 if digest_changed else digest, mode=current_mode, build=build)
                with patch('server.fetch', side_effect=fetch), patch('server.PINNED_SHA', digest), patch('server.subprocess.Popen', return_value=process) as download, patch.object(self.manager, 'probe', side_effect=RuntimeError('candidate checked')), patch.object(self.manager, 'stop') as stop:
                    with self.assertRaisesRegex(RuntimeError, 'candidate checked'):
                        self.manager.install()
                    download.assert_called_once(); stop.assert_not_called()

    def test_missing_or_changed_downloaded_build_never_stops_working_server(self):
        for build in (None, '1001'):
            with self.subTest(build=build):
                fetch, process, digest = self.install_fixture()
                original = process.__enter__.side_effect
                def download():
                    result = original()
                    for stage in (self.base / 'releases').iterdir():
                        if not (stage / 'hearth.json').exists():
                            manifest = stage / 'steamapps/appmanifest_896660.acf'
                            if build is None: manifest.unlink()
                            else: manifest.write_text('"AppState" { "appid" "896660" "StateFlags" "4" "buildid" "'+build+'" }')
                    return result
                process.__enter__.side_effect = download
                with patch('server.fetch', side_effect=fetch), patch('server.PINNED_SHA', digest), patch('server.subprocess.Popen', return_value=process), patch.object(self.manager, 'stop') as stop, patch.object(self.manager, 'probe') as probe:
                    with self.assertRaisesRegex(RuntimeError, 'сборк|Сборка'):
                        self.manager.install()
                    stop.assert_not_called(); probe.assert_not_called()

    def test_check_failure_does_not_claim_up_to_date_or_download(self):
        fetch, _, digest = self.install_fixture()
        self.up_to_date_release(digest)
        with patch('server.fetch', side_effect=fetch), patch('server.PINNED_SHA', digest), patch.object(self.manager, 'latest_steam_build', side_effect=RuntimeError('metadata unavailable')), patch('server.subprocess.Popen') as download, patch.object(self.manager, 'stop') as stop:
            with self.assertRaisesRegex(RuntimeError, 'metadata unavailable'):
                self.manager.install()
            download.assert_not_called(); stop.assert_not_called()

    def test_author_compatibility_missing_or_ambiguous_is_advisory(self):
        for body in (None, 'Valheim 1.0.15 and Valheim 1.0.16'):
            with patch('server.fetch', return_value={'tag_name':'10.4.0.0','body':body}):
                self.assertIsNone(self.manager.latest_release()[0])

    def test_no_update_worker_preserves_clear_result_message(self):
        result = {'updated': False, 'message': 'Обновлений нет: сервер и мод уже актуальны.'}
        with patch.object(self.manager, 'install', return_value=result), patch.object(self.manager.operations, 'notify') as notify:
            self.manager.submit('install')
            with self.manager.lock: pass
        self.assertEqual(self.manager.job, {'state':'done','message':result['message']})
        notify.assert_not_called()

    def test_probe_uses_private_config_copy_and_never_changes_original(self):
        folder = self.base / 'releases/candidate'; folder.mkdir()
        config = self.base / 'config/plugin/settings.cfg'; config.parent.mkdir()
        config.write_text('enabled = true')
        self.manager.copy_probe_config(folder)
        copied = folder / 'BepInEx/config/plugin/settings.cfg'
        self.assertFalse(copied.is_symlink())
        self.assertEqual(copied.read_text(), 'enabled = true')
        copied.write_text('changed by candidate')
        self.assertEqual(config.read_text(), 'enabled = true')

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
        with patch('server.fetch', side_effect=fetch), patch('server.subprocess.Popen', return_value=process), patch('server.PINNED_SHA', digest), patch.object(self.manager, 'probe', return_value='1.0.15'), patch.object(self.manager, 'start'), patch.object(self.manager, 'wait_ready', side_effect=failed_start):
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
        for output in [lines, lines+'HarmonyException: bad patch\nGame server connected\n', lines.replace('0.10.2.0', '0.10.1.0')+'Game server connected\n', lines+'Game server connected\n[Error : Another Mod] load failed\n']:
            process = MagicMock(stdout=io.StringIO(output))
            process.poll.return_value = None
            process.returncode = 0
            with patch.object(self.manager, 'spawn', return_value=process), patch.object(self.manager, 'halt'):
                with self.assertRaises(RuntimeError):
                    self.manager.probe(self.base, '1.0.15', '0.10.2.0')

    def test_probe_accepts_actual_version_only_after_stable_window(self):
        process = MagicMock(stdout=io.StringIO('Valheim version: 1.0.16\nBepInEx 5.4.23\nLoading [Valheim Plus 0.10.2.0]\nGame server connected\n'))
        process.poll.return_value = None; process.returncode = 0
        ticks = iter(range(1000))
        with patch.object(self.manager, 'spawn', return_value=process), patch.object(self.manager, 'halt'), patch('server.PROBE_STABLE_SECONDS', 5), patch('server.time.monotonic', side_effect=lambda: next(ticks)) as clock:
            self.assertEqual(self.manager.probe(self.base, '1.0.15', '0.10.2.0'), '1.0.16')
        self.assertGreaterEqual(clock.call_count, 7)

    def test_probe_rejects_late_plugin_error_clean_exit_failure_and_log_failure(self):
        output = 'Valheim version: 1.0.16\nGame server connected\n'
        for failure in ('shutdown_log', 'exit', 'log_reader', 'hung'):
            with self.subTest(failure=failure):
                process = MagicMock(stdout=io.StringIO(output)); process.poll.return_value = None; process.returncode = 0
                if failure == 'exit': process.returncode = 1
                def halt(_):
                    if failure == 'shutdown_log':
                        server.observe_startup(markers, '[Error : Third Party] startup failed')
                    elif failure == 'hung': raise RuntimeError('hung')
                # Inject a shutdown-only error through observe_startup's shared
                # marker dict, after the initial ready window has completed.
                markers = {}
                original = server.observe_startup
                def observe(current, line):
                    nonlocal markers
                    markers = current
                    return original(current, line)
                with patch.object(self.manager, 'spawn', return_value=process), patch.object(self.manager, 'halt', side_effect=halt), patch('server.observe_startup', side_effect=observe), patch.object(self.manager, 'say', side_effect=OSError('disk full') if failure == 'log_reader' else None):
                    with self.assertRaises(RuntimeError):
                        self.manager.probe(self.base, None, None)
                if failure == 'hung': process.kill.assert_called_once()

    def test_maintenance_deadline_after_probe_preserves_live_release(self):
        self.release('old')
        fetch, process, digest = self.install_fixture()
        with patch('server.fetch', side_effect=fetch), patch('server.PINNED_SHA', digest), patch('server.subprocess.Popen', return_value=process), patch.object(self.manager, 'probe', return_value='1.0.16'), patch.object(self.manager, 'guard_maintenance', side_effect=ValueError('deadline')), patch.object(self.manager, 'stop') as stop:
            with self.assertRaisesRegex(ValueError, 'deadline'):
                self.manager.install()
            stop.assert_not_called()
        self.assertEqual(self.manager.state['active'], 'old')

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

    def test_players_requires_auth_and_csrf_before_changing_lists(self):
        manager = server.Handler.manager
        body = {'action': 'ban', 'steam_id': '76561198000000001'}
        headers = {'Content-Type': 'application/json', 'X-Hearth': '1'}
        with patch.object(manager.player_access, 'perform') as perform:
            self.assertEqual(self.request('POST', '/api/players', body, headers)[0], 403)
            headers = self.login()
            for token in [None, 'wrong']:
                bad = dict(headers)
                if token is None:
                    bad.pop('X-CSRF-Token')
                else:
                    bad['X-CSRF-Token'] = token
                self.assertEqual(self.request('POST', '/api/players', body, bad)[0], 403)
            perform.assert_not_called()

    def test_player_access_changes_are_private_and_return_current_lists(self):
        manager = server.Handler.manager
        banned = manager.base / 'saves/bannedlist.txt'
        original = banned.read_bytes() if banned.exists() else None
        steam_id = '76561198000000001'
        try:
            headers = self.login()
            status, _, raw = self.request('POST', '/api/players', {'action': 'ban', 'steam_id': steam_id}, headers)
            self.assertEqual(status, 200)
            result = json.loads(raw)
            self.assertIsInstance(result['message'], str)
            self.assertIn(steam_id, result['access']['banned'])
            status = json.loads(self.request('GET', '/api/status', headers=headers)[2])
            self.assertIn(steam_id, status['player_access']['banned'])
            public = self.request('GET', '/api/public')[2]
            self.assertNotIn(steam_id.encode(), public)
            self.assertNotIn('player_access', json.loads(public))
        finally:
            if original is None:
                banned.unlink(missing_ok=True)
            else:
                banned.write_bytes(original)

    def test_player_action_lock_failure_does_not_run_or_report_success(self):
        manager = server.Handler.manager
        headers = self.login()
        manager.lock.acquire()
        try:
            with patch.object(manager.player_access, 'perform') as perform:
                status, _, raw = self.request('POST', '/api/players', {'action': 'admin', 'steam_id': '76561198000000001'}, headers)
                self.assertEqual(status, 400)
                self.assertIn('error', json.loads(raw))
                self.assertNotIn('message', json.loads(raw))
                perform.assert_not_called()
        finally:
            manager.lock.release()

    def test_player_action_validation_and_write_errors_release_operation_lock(self):
        manager = server.Handler.manager
        headers = self.login()
        body = {'action': 'ban', 'steam_id': '76561198000000001\nSteam_76561198000000002'}
        self.assertEqual(self.request('POST', '/api/players', body, headers)[0], 400)
        body['steam_id'] = '76561198000000001'
        with patch.object(manager.player_access, 'perform', side_effect=OSError('disk full')):
            status, _, raw = self.request('POST', '/api/players', body, headers)
        self.assertEqual(status, 500)
        self.assertIn('error', json.loads(raw))
        self.assertNotIn('message', json.loads(raw))
        self.assertTrue(manager.lock.acquire(blocking=False))
        manager.lock.release()

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
            self.assertIn('data-mods hidden',page)
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
        self.assertEqual(set(data), {'title','description','description_en','address','community_url','running','players','game','mod','server_name','mode','site_url','public_listing','maintenance','client_mods','launcher'})
        self.assertEqual(set(data['launcher']), {'version', 'windows', 'linux', 'windows_portable', 'linux_portable'})
        for platform in ('windows', 'linux', 'windows_portable', 'linux_portable'):
            self.assertEqual(set(data['launcher'][platform]), {'url', 'sha256', 'size', 'checksum_url'})
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
        self.assertNotIn(b'Loki-Mod-Installer.exe', self.request('GET', '/')[2])

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
        self.assertNotIn(b'Loki-Mod-Installer-Linux.sh', html)
        self.assertIn(b'bash Hearth-Launcher-Install-Linux.sh', html)
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
