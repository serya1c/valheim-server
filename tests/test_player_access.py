import os
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
        self.manager = SimpleNamespace(base=self.base, running=Mock(return_value=True), store=Mock())
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
