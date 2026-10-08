"""File bridge boundaries and builtin packaging; no game code is executed."""
import hashlib
import collections
import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import tarfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import game_admin
import server

STEAM = '76561198000000001'
OTHER = '76561198000000002'
SESSION = 'a' * 32


class GameAdminTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.manager = server.Manager(self.base)
        release = self.base / 'releases/fixture'
        release.mkdir()
        server.atomic_json(release / 'hearth.json', {'mode': 'plus', 'game': '1.0.17', 'mod': '0.10.2.0'})
        self.manager.state['active'] = 'fixture'
        self.manager.proc = MagicMock()
        self.manager.proc.poll.return_value = None
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('manifest.json', json.dumps({'version_number': '0.4.0', 'dependencies': []}))
            archive.writestr('BepInEx/plugins/ValheimAdminRu/ValheimAdminRu.dll', b'MZfixture')
        package = self.base / 'builtin.zip'
        package.write_bytes(stream.getvalue())
        self.manager.mods.install_builtin(package, hashlib.sha256(package.read_bytes()).hexdigest())
        self.bridge = self.manager.game_admin
        self.snapshot()

    def tearDown(self):
        for handler in self.manager.log.handlers[:]:
            handler.close()
            self.manager.log.removeHandler(handler)
        self.temp.cleanup()

    def snapshot(self, **overrides):
        root = ET.Element('status', {'protocol': '1', 'session': SESSION, 'at': str(time.time()),
                                    'mod': '0.4.0', 'game': '1.0.17', 'world': 'North', **overrides})
        players = ET.SubElement(root, 'players')
        for steam in (STEAM, OTHER):
            player = ET.SubElement(players, 'player', {'steam_id': steam, 'identity': 'Steam_' + steam,
                'name': '<script>Игрок</script>', 'ready': 'true', 'alive': 'true', 'role': 'None'})
            ET.SubElement(ET.SubElement(player, 'points'), 'point', {'id': 'c' * 32, 'name': 'Дом', 'x': '1', 'y': '2', 'z': '3'})
        ET.SubElement(ET.SubElement(root, 'items'), 'entry', {'prefab': 'Wood', 'name': 'Wood'})
        game_admin._atomic(self.bridge.root / 'status.xml', root)

    def command(self, **overrides):
        return {'action': 'GodSelf', 'session': SESSION, 'actor_steam': STEAM, 'enabled': True, **overrides}

    def test_snapshot_keeps_ids_and_player_text_literal(self):
        view = self.bridge.view()
        self.assertTrue(view['available'], view)
        self.assertEqual(view['players'][0]['steam_id'], STEAM)
        self.assertEqual(view['players'][0]['name'], '<script>Игрок</script>')
        self.assertEqual(view['items'], [{'prefab': 'Wood', 'name': 'Wood', 'name_en': 'Wood'}])
        self.assertEqual(view['players'][0]['points'][0]['id'], 'c' * 32)

    def test_atomic_command_pending_and_acknowledgement(self):
        response = self.bridge.submit(self.command())
        identifier = response['id']
        path = self.bridge.root / f'command-{identifier}.xml'
        root = ET.parse(path).getroot()
        self.assertEqual(root.get('actor_steam'), STEAM)
        self.assertLess(float(root.get('expires')), time.time() + 31)
        self.assertEqual(self.bridge.result(identifier)['state'], 'pending')
        game_admin._atomic(self.bridge.root / f'result-{identifier}.xml', ET.Element('result', {
            'id': identifier, 'session': SESSION, 'success': 'true', 'message': 'done', 'at': str(time.time())}))
        self.assertEqual(self.bridge.result(identifier)['state'], 'done')

    def test_validation_rejects_arbitrary_or_unsafe_commands(self):
        for changes in ({'action': 'BanPlayer'}, {'action': 'exec'}, {'actor_steam': int(STEAM)},
                {'count': True}, {'count': 501}, {'radius': 41}, {'height': float('nan')},
                {'x': float('inf')}, {'z': 10501}, {'enabled': 'true'}, {'extra': 'field'},
                {'role': 'Owner'}, {'text': 'bad\x00text'}, {'hammer_targets': 16}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.bridge.submit(self.command(**changes))
        self.assertFalse(list(self.bridge.root.glob('command-*')))

    def test_target_and_saved_point_validation(self):
        with self.assertRaises(ValueError): self.bridge.submit(self.command(action='HealPlayer'))
        with self.assertRaises(ValueError): self.bridge.submit(self.command(action='TeleportSaved', point_id='../escape'))
        result = self.bridge.submit(self.command(action='TeleportSaved', point_id='c' * 32))
        self.assertEqual(result['state'], 'pending')
        with self.assertRaises(ValueError): self.bridge.submit(self.command(action='SpawnMob', prefab='Boar', count=21))

    def test_stale_world_offline_or_wrong_version_cannot_queue(self):
        for changes in ({'session': 'b' * 32}, {'at': str(time.time() - 20)}, {'mod': '0.3.1'}):
            self.snapshot(**changes)
            with self.assertRaises(ValueError): self.bridge.submit(self.command())
        self.snapshot()
        self.manager.proc = None
        with self.assertRaises(ValueError): self.bridge.submit(self.command())
        self.assertFalse(list(self.bridge.root.glob('command-*')))

    def test_timeout_does_not_claim_success_and_clears_queued_file(self):
        identifier = self.bridge.submit(self.command())['id']
        self.bridge.requests[identifier]['expires'] = time.time() - 1
        self.assertEqual(self.bridge.result(identifier)['state'], 'error')
        self.assertIn('неизвестен', self.bridge.result(identifier)['message'])
        self.assertFalse((self.bridge.root / f'command-{identifier}.xml').exists())

    def test_world_switch_and_restart_never_replay(self):
        identifier = self.bridge.submit(self.command())['id']
        self.snapshot(session='b' * 32)
        self.assertEqual(self.bridge.result(identifier)['state'], 'error')
        self.bridge.prepare_start()
        self.assertFalse(list(self.bridge.root.glob('*.xml')))
        with self.assertRaises(ValueError): self.bridge.result(identifier)

    def test_pending_survives_maintenance_and_temporarily_stale_telemetry(self):
        identifier = self.bridge.submit(self.command())['id']
        self.manager.busy = True
        self.assertFalse(self.bridge.view()['available'])
        self.assertEqual(self.bridge.result(identifier)['state'], 'pending')
        self.snapshot(at=str(time.time() - 20))
        self.assertEqual(self.bridge.result(identifier)['state'], 'pending')
        self.bridge.requests[identifier]['expires'] = time.time() - 1
        self.assertEqual(self.bridge.result(identifier)['state'], 'error')

    def test_rejects_foreign_ack_and_xml_entities(self):
        identifier = self.bridge.submit(self.command())['id']
        game_admin._atomic(self.bridge.root / f'result-{identifier}.xml', ET.Element('result', {
            'id': identifier, 'session': 'b' * 32, 'success': 'true'}))
        with self.assertRaises(ValueError): self.bridge.result(identifier)
        (self.bridge.root / 'status.xml').write_text('<!DOCTYPE x [<!ENTITY e "bad">]><status/>')
        self.assertFalse(self.bridge.view()['available'])

    def test_corrupt_snapshot_clears_partial_availability(self):
        path = self.bridge.root / 'status.xml'
        root = ET.parse(path).getroot()
        root.find('./players/player').set('x', 'nan')
        game_admin._atomic(path, root)
        view = self.bridge.view()
        self.assertFalse(view['available'])
        self.assertIsNone(view['session'])
        self.assertEqual(view['players'], [])
        json.dumps(view, allow_nan=False)

    def test_bounded_queue_and_unknown_result(self):
        for _ in range(16): self.bridge.submit(self.command())
        with self.assertRaises(ValueError): self.bridge.submit(self.command())
        with self.assertRaises(ValueError): self.bridge.result('../status')

    def test_confirmed_commands_do_not_exhaust_pending_queue(self):
        for _ in range(20):
            identifier = self.bridge.submit(self.command())['id']
            game_admin._atomic(self.bridge.root / f'result-{identifier}.xml', ET.Element('result', {
                'id': identifier, 'session': SESSION, 'success': 'true', 'message': 'done'}))
            self.assertEqual(self.bridge.result(identifier)['state'], 'done')
        self.assertEqual(self.bridge.submit(self.command())['state'], 'pending')

    def test_builtin_hash_scope_persistence_and_client_privacy(self):
        packages = self.manager.mods.view()['packages']
        self.assertEqual(packages[0]['source'], 'builtin')
        self.assertEqual(packages[0]['scope'], 'both')
        reloaded = server.ModManager(self.base)
        self.assertEqual(reloaded.view()['packages'], packages)
        archive = reloaded.client_archive()
        with zipfile.ZipFile(archive) as bundle:
            self.assertTrue(any(name.endswith('ValheimAdminRu.dll') for name in bundle.namelist()))
            self.assertFalse(any('config' in name or 'admin-bridge' in name for name in bundle.namelist()))
        with self.assertRaises(ValueError): reloaded.install_builtin(self.base / 'builtin.zip', '0' * 64)

    def test_bundled_artifact_contains_only_plugin_and_public_metadata(self):
        info = game_admin.builtin_info()
        self.assertIsNotNone(info)
        self.assertEqual(hashlib.sha256(game_admin.BUNDLE.read_bytes()).hexdigest(), info['sha256'])
        with zipfile.ZipFile(game_admin.BUNDLE) as archive:
            self.assertEqual(set(archive.namelist()), {'BepInEx/plugins/ValheimAdminRu/ValheimAdminRu.dll', 'manifest.json', 'README.md'})
            self.assertEqual(json.loads(archive.read('manifest.json'))['version_number'], info['version'])

    def test_live_process_receives_bridge_but_probe_does_not(self):
        release = self.manager.active()
        (release / 'valheim_server.x86_64').write_bytes(b'fixture executable')
        with patch.object(server.subprocess, 'Popen') as start:
            self.manager.spawn(release, self.base / 'saves', 2456)
            self.assertEqual(start.call_args.kwargs['env']['HEARTH_ADMIN_BRIDGE'], str(self.bridge.root))
            self.manager.spawn(release, self.base / 'saves', 2456, probe=True)
            self.assertNotIn('HEARTH_ADMIN_BRIDGE', start.call_args.kwargs['env'])

    def test_builtin_operation_preserves_config_and_distributes_identical_dll(self):
        self.manager.proc = None
        config = self.base / 'config/ValheimAdminRu/roles.xml'
        config.parent.mkdir(parents=True)
        config.write_text('<roles/>')
        self.manager.change_mods('mod_builtin', {})
        package = self.manager.mods.view()['packages'][0]
        self.assertEqual(package['source'], 'builtin')
        self.assertEqual(package['version'], game_admin.builtin_info()['version'])
        installed = next((self.manager.active() / 'BepInEx/plugins/HearthMods').rglob('ValheimAdminRu.dll')).read_bytes()
        with zipfile.ZipFile(self.base / 'client-mods.zip') as archive:
            path = next(name for name in archive.namelist() if name.endswith('ValheimAdminRu.dll'))
            self.assertEqual(archive.read(path), installed)
        self.assertEqual(config.read_text(), '<roles/>')
        with tarfile.open(next((self.base / 'backups').glob('*-pre-mods.tar.gz'))) as archive:
            self.assertEqual(archive.extractfile('config/ValheimAdminRu/roles.xml').read(), b'<roles/>')
            self.assertFalse(any('admin-bridge' in name for name in archive.getnames()))

    def test_builtin_install_conflicts_do_not_stop_server(self):
        plugins = self.manager.active() / 'BepInEx/plugins/Legacy'
        plugins.mkdir(parents=True)
        (plugins / 'ValheimAdminRu.dll').write_bytes(b'MZlegacy')
        with patch.object(self.manager, 'stop') as stop:
            with self.assertRaisesRegex(ValueError, 'ручную установку'):
                self.manager.change_mods('mod_builtin', {})
            stop.assert_not_called()
        server.atomic_json(self.manager.active() / 'hearth.json', {'mode': 'plus', 'game': '1.0.18'})
        with patch.object(self.manager, 'stop') as stop:
            with self.assertRaisesRegex(ValueError, 'проверен только'):
                self.manager.change_mods('mod_builtin', {})
            stop.assert_not_called()


class GameAdminHttpTests(unittest.TestCase):
    # Share fixtures, without inheriting and duplicating all filesystem tests.
    snapshot = GameAdminTests.snapshot
    command = GameAdminTests.command

    def setUp(self):
        GameAdminTests.setUp(self)
        self.manager.panel.save({**self.manager.panel.load(), 'auth': server.password_hash('correct-long-password')})
        class Handler(server.Handler):
            sessions = {}
            attempts = collections.deque(maxlen=100)
        Handler.manager = self.manager
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        GameAdminTests.tearDown(self)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        connection.request(method, path, json.dumps(body) if body is not None else None, headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), json.loads(response.read())
        connection.close()
        return result

    def login(self):
        status, headers, value = self.request('POST', '/api/login', {'password': 'correct-long-password'},
                                            {'X-Hearth': '1', 'Content-Type': 'application/json'})
        self.assertEqual(status, 200)
        return {'Cookie': headers['Set-Cookie'].split(';')[0], 'X-Hearth': '1',
                'X-CSRF-Token': value['csrf'], 'Content-Type': 'application/json'}

    def test_bridge_private_and_post_csrf_protected(self):
        self.assertEqual(self.request('GET', '/api/game-admin')[0], 401)
        self.assertEqual(self.request('GET', '/api/game-admin/result?id=' + 'a' * 32)[0], 401)
        self.assertEqual(self.request('POST', '/api/game-admin', self.command())[0], 403)
        headers = self.login()
        headers['X-CSRF-Token'] = 'wrong'
        self.assertEqual(self.request('POST', '/api/game-admin', self.command(), headers)[0], 403)
        self.assertFalse(list(self.bridge.root.glob('command-*')))
        public = self.request('GET', '/api/public')[2]
        self.assertNotIn(STEAM, json.dumps(public))
        self.assertNotIn('audit', public)

    def test_queue_and_query_result_and_maintenance_lock(self):
        headers = self.login()
        self.assertTrue(self.request('GET', '/api/game-admin', headers=headers)[2]['available'])
        status, _, response = self.request('POST', '/api/game-admin', self.command(), headers)
        self.assertEqual(status, 202)
        self.assertEqual(self.request('GET', '/api/game-admin/result?id=' + response['id'], headers=headers)[2]['state'], 'pending')
        with self.manager.lock:
            self.assertEqual(self.request('POST', '/api/game-admin', self.command(), headers)[0], 400)
            # Read-only view must remain responsive during maintenance.
            self.assertEqual(self.request('GET', '/api/game-admin', headers=headers)[0], 200)


if __name__ == '__main__':
    unittest.main()
