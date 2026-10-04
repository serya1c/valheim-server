import os
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from player_access import PlayerAccess


STEAM_ID = '76561198000000001'
OTHER_ID = '76561198000000002'
NATIVE_ID = 'Steam_' + STEAM_ID


class PlayerAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / 'saves').mkdir()
        self.manager = SimpleNamespace(base=self.base, running=Mock(return_value=True), store=Mock(), operations=Mock())
        self.access = PlayerAccess(self.manager)
        self.admins = self.base / 'saves/adminlist.txt'
        self.bans = self.base / 'saves/bannedlist.txt'

    def tearDown(self):
        self.tmp.cleanup()

    def test_admin_and_ban_preserve_foreign_entries_and_whitelist(self):
        existing = '// Existing server rules\nPlayFab_someone\n192.0.2.7\n'
        permitted = self.base / 'saves/permittedlist.txt'
        permitted.write_text('// Whitelist\nSteam_' + OTHER_ID + '\n', encoding='utf-8')
        whitelist = permitted.read_bytes()
        for action, path, key in [('admin', self.admins, 'admins'), ('ban', self.bans, 'banned')]:
            with self.subTest(action=action):
                path.write_text(existing, encoding='utf-8')
                self.assertIsInstance(self.access.perform(action, STEAM_ID), str)
                self.access.perform(action, NATIVE_ID)
                text = path.read_text(encoding='utf-8')
                for line in existing.splitlines():
                    self.assertIn(line, text.splitlines())
                self.assertEqual(text.splitlines().count(NATIVE_ID), 1)
                self.assertEqual(self.access.view()[key], [STEAM_ID])
        self.assertEqual(permitted.read_bytes(), whitelist)

    def test_legacy_entries_are_equivalent_and_both_forms_are_removed(self):
        for grant, revoke, path, key in [
            ('admin', 'unadmin', self.admins, 'admins'),
            ('ban', 'unban', self.bans, 'banned'),
        ]:
            with self.subTest(action=grant):
                path.write_text('// Keep\n' + STEAM_ID + '\n', encoding='utf-8')
                self.access.perform(grant, NATIVE_ID)
                self.assertEqual(path.read_text(encoding='utf-8').splitlines(), ['// Keep', STEAM_ID])
                path.write_text('// Keep\n' + STEAM_ID + '\n' + NATIVE_ID + '\nSteam_' + OTHER_ID + '\n', encoding='utf-8')
                self.access.perform(revoke, STEAM_ID)
                self.assertEqual(path.read_text(encoding='utf-8').splitlines(), ['// Keep', 'Steam_' + OTHER_ID])
                self.assertEqual(self.access.view()[key], [OTHER_ID])

    def test_invalid_id_and_action_cannot_change_lists(self):
        self.admins.write_text('// Original\n', encoding='utf-8')
        self.bans.write_text('// Original\n', encoding='utf-8')
        before = (self.admins.read_bytes(), self.bans.read_bytes())
        bad_ids = [None, 76561198000000001, '', '1' * 16, '1' * 18, 'a' * 17,
                   STEAM_ID + '\n', STEAM_ID + '\r\nSteam_' + OTHER_ID,
                   STEAM_ID + '\x00', 'Steam_' + STEAM_ID + '\t', '// ' + NATIVE_ID]
        for value in bad_ids:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.access.perform('ban', value)
        for action in [None, 'shell', 'kick\n', 'permitted']:
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.access.perform(action, STEAM_ID)
        self.assertEqual((self.admins.read_bytes(), self.bans.read_bytes()), before)

    def test_kick_requires_running_server_and_protects_permanent_bans(self):
        self.manager.running.return_value = False
        with self.assertRaises(ValueError):
            self.access.perform('kick', STEAM_ID)
        self.assertFalse(self.bans.exists())
        self.manager.running.return_value = True
        for identifier in [STEAM_ID, NATIVE_ID]:
            with self.subTest(identifier=identifier):
                original = '// Permanent ban\n' + identifier + '\n'
                self.bans.write_text(original, encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.access.perform('kick', STEAM_ID)
                with patch('player_access.time.time', return_value=2000):
                    self.access.cleanup(force=True)
                self.assertEqual(self.bans.read_text(encoding='utf-8'), original)
                self.assertEqual(self.access.view()['banned'], [STEAM_ID])

    def test_kick_expires_after_panel_restart_and_native_comment_reordering(self):
        self.bans.write_text('// Rules\nSteam_' + OTHER_ID + '\n', encoding='utf-8')
        with patch('player_access.time.time', return_value=1000):
            self.access.perform('kick', NATIVE_ID)
            self.assertEqual(self.access.view()['kicks'], [{'steam_id': STEAM_ID, 'until': 1030}])
            self.assertEqual(self.access.view()['banned'], [OTHER_ID])
            with self.assertRaises(ValueError):
                self.access.perform('kick', STEAM_ID)
        # Valheim moves comments to the top when rewriting its access lists.
        lines = self.bans.read_text(encoding='utf-8').splitlines()
        lines.sort(key=lambda line: not line.startswith('//'))
        self.bans.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        restarted = PlayerAccess(self.manager)
        with patch('player_access.time.time', return_value=1029):
            restarted.cleanup()
            self.assertIn(NATIVE_ID, self.bans.read_text(encoding='utf-8').splitlines())
        with patch('player_access.time.time', return_value=1031):
            restarted.cleanup()
        self.assertEqual(self.bans.read_text(encoding='utf-8').splitlines(), ['// Rules', 'Steam_' + OTHER_ID])
        self.assertEqual(restarted.view()['kicks'], [])

    def test_cleanup_preserves_new_permanent_legacy_entry_for_same_player(self):
        with patch('player_access.time.time', return_value=1000):
            self.access.perform('kick', STEAM_ID)
        with self.bans.open('a', encoding='utf-8') as stream:
            stream.write(STEAM_ID + '\n// Added by another admin\nPlayFab_keep\n')
        with patch('player_access.time.time', return_value=1031):
            PlayerAccess(self.manager).cleanup()
        lines = self.bans.read_text(encoding='utf-8').splitlines()
        self.assertIn(STEAM_ID, lines)
        self.assertIn('// Added by another admin', lines)
        self.assertIn('PlayFab_keep', lines)
        self.assertNotIn(NATIVE_ID, lines)
        self.assertEqual(self.access.view()['banned'], [STEAM_ID])

    def test_ban_promotes_temporary_kick_to_permanent(self):
        with patch('player_access.time.time', return_value=1000):
            self.access.perform('kick', STEAM_ID)
            self.access.perform('ban', STEAM_ID)
        with patch('player_access.time.time', return_value=2000):
            PlayerAccess(self.manager).cleanup(force=True)
        self.assertEqual(self.bans.read_text(encoding='utf-8').splitlines(), [NATIVE_ID])
        self.assertEqual(self.access.view()['banned'], [STEAM_ID])
        self.assertEqual(self.access.view()['kicks'], [])

    def test_mutation_advances_mtime_even_when_old_file_is_in_future(self):
        self.bans.write_text('// Rules\n', encoding='utf-8')
        with patch('player_access.time.time', return_value=1000):
            os.utime(self.bans, (2000, 2000))
            before = self.bans.stat().st_mtime
            self.access.perform('ban', STEAM_ID)
        self.assertGreater(self.bans.stat().st_mtime, before)

    def test_read_and_write_failures_are_not_reported_as_success(self):
        self.bans.write_text('// Original\n', encoding='utf-8')
        original = self.bans.read_bytes()
        with patch('player_access.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(ValueError):
                self.access.perform('ban', STEAM_ID)
        self.assertEqual(self.bans.read_bytes(), original)
        with patch.object(Path, 'open', side_effect=PermissionError('access denied')):
            with self.assertRaises(ValueError):
                self.access.perform('ban', STEAM_ID)
            self.assertTrue(self.access.view()['error'])

    def test_concurrent_external_update_is_preserved_instead_of_overwritten(self):
        self.bans.write_text('// Original\n', encoding='utf-8')
        external = '// Saved by the game during the panel request\nSteam_' + OTHER_ID + '\n'

        def external_change(*_):
            self.bans.write_text(external, encoding='utf-8')

        with patch('player_access.os.utime', side_effect=external_change):
            with self.assertRaises(ValueError):
                self.access.perform('ban', STEAM_ID)
        self.assertEqual(self.bans.read_text(encoding='utf-8'), external)
        self.assertEqual(list((self.base / 'saves').glob('*.tmp')), [])

    def test_timed_ban_survives_force_cleanup_then_expires_after_restart(self):
        with patch('player_access.time.time', return_value=1000):
            self.access.perform('ban', STEAM_ID, duration_hours=1, reason='Repeated griefing')
            self.access.cleanup(force=True)
        native = self.bans.read_text(encoding='utf-8')
        self.assertNotIn('Repeated griefing', native)
        lines = native.splitlines()
        lines.sort(key=lambda line: not line.startswith('//'))
        self.bans.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        restarted = PlayerAccess(self.manager)
        self.assertEqual(restarted.view()['timed_bans'], [{'steam_id':STEAM_ID, 'until':4600, 'reason':'Repeated griefing'}])
        self.assertEqual(restarted.view()['banned'], [])
        with patch('player_access.time.time', return_value=4600):
            restarted.cleanup()
            restarted.cleanup()
        self.assertEqual(restarted.view()['timed_bans'], [])
        self.assertNotIn(NATIVE_ID, self.bans.read_text(encoding='utf-8'))
        self.assertEqual([item['action'] for item in restarted.view()['history']], ['expiry', 'ban'])
        self.assertEqual(self.manager.operations.notify.call_count, 2)

    def test_timed_ban_does_not_weaken_permanent_or_external_bans(self):
        for native in [STEAM_ID, NATIVE_ID]:
            self.bans.write_text(native + '\n', encoding='utf-8')
            original = self.bans.read_bytes()
            with self.assertRaises(ValueError):
                self.access.perform('ban', STEAM_ID, duration_hours=1)
            self.assertEqual(self.bans.read_bytes(), original)
        self.bans.write_text('', encoding='utf-8')
        with patch('player_access.time.time', return_value=1000):
            self.access.perform('ban', STEAM_ID, duration_hours=1)
        with self.bans.open('a', encoding='utf-8') as file:
            file.write(STEAM_ID + '\n' + NATIVE_ID + '\n// External ban\n')
        with patch('player_access.time.time', return_value=4601):
            self.access.cleanup()
        self.assertEqual(self.bans.read_text(encoding='utf-8').splitlines(), [STEAM_ID, NATIVE_ID, '// External ban'])
        self.assertEqual(self.access.view()['banned'], [STEAM_ID])

    def test_kick_can_be_promoted_to_timed_or_permanent_ban(self):
        with patch('player_access.time.time', return_value=1000):
            self.access.perform('kick', STEAM_ID)
            self.access.act('ban', STEAM_ID, until=2000, reason='Temporary restriction')
            self.access.cleanup(force=True)
            self.assertEqual(self.access.view()['kicks'], [])
            self.assertEqual(self.access.view()['timed_bans'][0]['until'], 2000)
            self.access.perform('ban', STEAM_ID, reason='Permanent restriction')
        with patch('player_access.time.time', return_value=5000):
            self.access.cleanup(force=True)
        self.assertEqual(self.access.view()['timed_bans'], [])
        self.assertEqual(self.access.view()['banned'], [STEAM_ID])
        self.assertEqual(self.access.view()['ban_details'][STEAM_ID]['reason'], 'Permanent restriction')

    def test_invalid_ban_duration_and_text_never_change_files(self):
        self.bans.write_text('// Original\n', encoding='utf-8')
        original = self.bans.read_bytes()
        bad = [{'duration_hours':value} for value in [True, '1', 0, -1, 1/120, 8761, float('inf'), float('nan')]]
        bad += [{'until':value} for value in [True, '2000', 1001, 1000+366*86400]]
        bad += [{'duration_hours':1,'until':2000}, {'reason':'a'*301}, {'reason':'reason\nforged log'}, {'reason':'reason\u0085forged log'}, {'reason':None}]
        with patch('player_access.time.time', return_value=1000):
            for options in bad:
                with self.subTest(options=options), self.assertRaises(ValueError):
                    self.access.perform('ban', STEAM_ID, **options)
        self.assertEqual(self.bans.read_bytes(), original)
        self.assertFalse((self.base / 'moderation.json').exists())

    def test_private_profiles_and_history_persist_outside_game_saves(self):
        self.access.perform('profile', STEAM_ID, alias='Private alias', notes='Private note\nSecond line')
        self.access.perform('ban', STEAM_ID, reason='Public reason @everyone <@123>')
        self.access.perform('unban', STEAM_ID)
        view = PlayerAccess(self.manager).view()
        self.assertEqual(view['profiles'][STEAM_ID], {'alias':'Private alias', 'notes':'Private note\nSecond line'})
        self.assertEqual([item['action'] for item in view['history']], ['unban', 'ban', 'profile'])
        native = self.bans.read_text(encoding='utf-8')
        self.assertNotIn('Private', native)
        self.assertFalse((self.base / 'saves/moderation.json').exists())
        self.assertTrue((self.base / 'moderation.json').is_file())
        notifications = str(self.manager.operations.notify.call_args_list)
        self.assertIn('Public reason', notifications)
        self.assertNotIn('Private alias', notifications)
        self.assertNotIn('Private note', notifications)
        self.assertNotIn('@everyone', notifications)
        self.assertNotIn('<@123>', notifications)

    def test_restored_native_timer_controls_expiry_without_using_newer_private_reason(self):
        with patch('player_access.time.time', return_value=1000):
            self.access.perform('ban', STEAM_ID, until=2000, reason='Reason from the newer server state')
        native = '// Hearth timed ban Steam_' + STEAM_ID + ' until 3000\n' + NATIVE_ID + '\n'
        self.bans.write_text(native, encoding='utf-8')
        self.assertEqual(self.access.view()['timed_bans'], [{'steam_id':STEAM_ID,'until':3000,'reason':''}])
        with patch('player_access.time.time', return_value=2500):
            PlayerAccess(self.manager).cleanup(force=True)
        self.assertIn(NATIVE_ID, self.bans.read_text(encoding='utf-8'))
        with patch('player_access.time.time', return_value=3000):
            self.access.cleanup()
        self.assertEqual(self.access.view()['timed_bans'], [])
        self.assertNotIn('Reason from the newer server state', self.manager.operations.notify.call_args.args[1])

    def test_metadata_save_failure_reverts_native_action_and_does_not_notify(self):
        self.bans.write_text('// Existing rule\nSteam_' + OTHER_ID + '\n', encoding='utf-8')
        original = self.bans.read_bytes()
        replace = os.replace

        def fail_metadata(source, target):
            if Path(target) == self.base / 'moderation.json':
                raise OSError('secret disk error')
            return replace(source, target)

        with patch('player_access.os.replace', side_effect=fail_metadata):
            with self.assertRaises(ValueError) as caught:
                self.access.perform('ban', STEAM_ID, reason='Reason')
        self.assertNotIn('secret disk error', str(caught.exception))
        self.assertEqual(self.bans.read_bytes(), original)
        self.assertEqual(self.access.view()['history'], [])
        self.manager.operations.notify.assert_not_called()

    def test_history_is_bounded_and_corrupt_metadata_prevents_unaudited_actions(self):
        self.access.perform('admin', STEAM_ID)
        path = self.base / 'moderation.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['history'] = data['history'] * 200
        path.write_text(json.dumps(data), encoding='utf-8')
        self.access.perform('unadmin', STEAM_ID)
        view = self.access.view()
        self.assertEqual(len(view['history']), 200)
        self.assertEqual(view['history'][0]['action'], 'unadmin')
        path.write_text('{ broken: secret', encoding='utf-8')
        with self.assertRaises(ValueError) as caught:
            self.access.perform('ban', STEAM_ID)
        self.assertNotIn('secret', str(caught.exception))
        self.assertFalse(self.bans.exists())
        self.assertTrue(self.access.view()['error'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
