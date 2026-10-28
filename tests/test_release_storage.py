import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import release_storage
import server

ACTIVE = 'plus-' + 'a' * 16
PREVIOUS = 'vanilla-' + 'b' * 16
OLD = 'modded-' + 'c' * 16
STAGE = 'plus-' + 'd' * 16


class ReleaseFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'releases'
        self.root.mkdir()
        self.state = {'active': ACTIVE, 'previous': PREVIOUS}
        for name in [ACTIVE, PREVIOUS, OLD]:
            self.release(name)
        self.save_state()

    def release(self, name):
        path = self.root / name
        path.mkdir()
        (path / 'hearth.json').write_text(json.dumps({'game': '1.0.20'}))
        (path / 'server.bin').write_bytes(b'server')
        return path

    def save_state(self):
        (self.base / 'state.json').write_text(json.dumps(self.state))

    def prune(self):
        return release_storage.prune_releases(self.base, self.state)

    def link(self, path, target):
        try:
            path.symlink_to(target, target_is_directory=True)
        except OSError as error:
            self.skipTest(f'Symlinks unavailable: {error}')

class ReleaseStorageTests(ReleaseFixture, unittest.TestCase):
    def test_keeps_active_previous_and_unrelated_data(self):
        for folder in ['saves', 'config', 'backups']:
            (self.base / folder).mkdir()
            (self.base / folder / 'keep').write_text('unchanged')
        (self.root / 'manual-installation').mkdir()
        self.assertEqual(self.prune(), [OLD])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), sorted([ACTIVE, PREVIOUS, 'manual-installation']))
        for folder in ['saves', 'config', 'backups']:
            self.assertEqual((self.base / folder / 'keep').read_text(), 'unchanged')

    def test_update_and_mod_recovery_keep_every_release(self):
        for key in ['update_trial', 'mods_trial']:
            with self.subTest(key=key):
                self.state[key] = True if key == 'update_trial' else 'restore.tar.gz'
                self.save_state()
                self.assertEqual(self.prune(), [])
                self.state.pop(key)
        self.assertTrue((self.root / OLD).exists())

    def test_missing_or_different_state_does_not_delete(self):
        (self.base / 'state.json').unlink()
        self.assertEqual(self.prune(), [])
        self.save_state()
        disk = {**self.state, 'previous': OLD}
        (self.base / 'state.json').write_text(json.dumps(disk))
        self.assertEqual(self.prune(), [])
        self.assertTrue((self.root / OLD).exists())

    def test_corrupt_state_cannot_delete_releases(self):
        for text in ['{broken', '[]', 'null']:
            with self.subTest(text=text):
                (self.base / 'state.json').write_text(text)
                with self.assertRaises(ValueError):
                    self.prune()
                self.assertTrue((self.root / OLD).exists())

    def test_invalid_trial_types_cannot_allow_cleanup(self):
        for field, value in [('update_trial', []), ('update_trial', 0), ('mods_trial', 0), ('mods_trial', '')]:
            with self.subTest(field=field, value=value):
                self.state[field] = value
                self.save_state()
                with self.assertRaises(ValueError):
                    self.prune()
                self.assertTrue((self.root / OLD).exists())
                self.state.pop(field)

    def test_invalid_or_missing_protected_release_keeps_everything(self):
        for value in ['../outside', '/tmp/world', 'missing', '', 123, None]:
            with self.subTest(active=value):
                self.state['active'] = value
                self.save_state()
                self.assertEqual(self.prune(), [])
                self.assertTrue((self.root / OLD).exists())

    def test_invalid_protected_metadata_does_not_delete(self):
        (self.root / PREVIOUS / 'hearth.json').write_text('{}')
        self.assertEqual(self.prune(), [])
        self.assertTrue((self.root / OLD).exists())

    def test_orphan_stage_without_metadata_is_removed(self):
        stage = self.root / STAGE
        stage.mkdir()
        (stage / 'partial-download').write_text('partial')
        self.assertEqual(set(self.prune()), {OLD, STAGE})

    def test_nested_config_link_keeps_its_external_target(self):
        config = self.base / 'config'
        config.mkdir()
        (config / 'valheim_plus.cfg').write_text('keep')
        (self.root / OLD / 'BepInEx').mkdir()
        self.link(self.root / OLD / 'BepInEx/config', config)
        self.assertEqual(self.prune(), [OLD])
        self.assertEqual((config / 'valheim_plus.cfg').read_text(), 'keep')

    def test_candidate_symlink_is_not_followed_or_removed(self):
        target = self.base / 'outside'
        target.mkdir()
        (target / 'keep').write_text('keep')
        self.link(self.root / STAGE, target)
        self.assertEqual(self.prune(), [OLD])
        self.assertTrue((self.root / STAGE).is_symlink())
        self.assertEqual((target / 'keep').read_text(), 'keep')

    def test_root_symlink_disables_cleanup(self):
        target = self.base / 'other-releases'
        self.root.rename(target)
        self.link(self.root, target)
        self.assertEqual(self.prune(), [])
        self.assertTrue((target / OLD).exists())

    def test_nested_mount_is_never_removed(self):
        mount = self.root / OLD / 'BepInEx/config'
        with patch('release_storage._mounts', return_value=[mount]):
            self.assertEqual(self.prune(), [])
        self.assertTrue((self.root / OLD).exists())

    def test_external_state_change_stops_remaining_deletions(self):
        self.release(STAGE)
        original = release_storage.shutil.rmtree

        def external_change(folder):
            original(folder)
            self.state['previous'] = STAGE
            self.save_state()

        with patch('release_storage.shutil.rmtree', side_effect=external_change):
            self.assertEqual(self.prune(), [OLD])
        self.assertTrue((self.root / STAGE).exists())


class ManagerRetentionTests(ReleaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.manager = server.Manager(self.base)

        def close_logs():
            for handler in self.manager.log.handlers[:]:
                handler.close()
                self.manager.log.removeHandler(handler)
        self.addCleanup(close_logs)

    def perform(self, action):
        threads = []
        real_thread = threading.Thread

        def thread(*args, **kwargs):
            result = real_thread(*args, **kwargs)
            threads.append(result)
            return result

        with patch('server.threading.Thread', side_effect=thread):
            self.manager.submit(action)
            threads[0].join(timeout=5)
        self.assertFalse(threads[0].is_alive())
        self.assertFalse(self.manager.busy)
        self.assertFalse(self.manager.lock.locked())

    def test_boot_cleanup_runs_under_mutation_lock(self):
        real_prune = release_storage.prune_releases

        def locked_prune(*args):
            self.assertTrue(self.manager.lock.locked())
            self.assertTrue(self.manager.busy)
            return real_prune(*args)

        with patch.object(self.manager, 'start'), patch('server.release_storage.prune_releases', side_effect=locked_prune):
            self.perform('start')
        self.assertFalse((self.root / OLD).exists())

    def test_committed_new_stage_is_kept_and_previous_generation_expires(self):
        def install():
            self.release(STAGE)
            self.manager.state.update(active=STAGE, previous=ACTIVE)
            self.manager.save_state()

        with patch.object(self.manager, 'install', side_effect=install):
            self.perform('install')
        self.assertEqual({p.name for p in self.root.iterdir()}, {STAGE, ACTIVE})

    def test_cleanup_and_logging_failure_do_not_fail_successful_action(self):
        with patch.object(self.manager, 'execute'), patch('server.release_storage.prune_releases', side_effect=OSError('disk error')), patch.object(self.manager, 'say', side_effect=OSError('log error')):
            self.perform('start')
        self.assertEqual(self.manager.job['state'], 'done')
        self.assertTrue((self.root / OLD).exists())

    def test_shutdown_skips_cleanup(self):
        self.manager.closing = True
        self.manager.prune_releases()
        self.assertTrue((self.root / OLD).exists())

    def test_unreferenced_live_process_prevents_deletion(self):
        self.manager.proc = MagicMock(args=[str(self.root / OLD / 'server.bin')])
        self.manager.proc.poll.return_value = None
        self.manager.prune_releases()
        self.assertTrue((self.root / OLD).exists())

    def test_active_live_process_allows_old_release_cleanup(self):
        self.manager.proc = MagicMock(args=[str(self.root / ACTIVE / 'server.bin')])
        self.manager.proc.poll.return_value = None
        self.manager.prune_releases()
        self.assertFalse((self.root / OLD).exists())


if __name__ == '__main__':
    unittest.main()
