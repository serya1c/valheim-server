"""V+ map migration, failure safety, and full-backup integration."""
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import server
from vplus_data import prepare_vplus_data


class VPlusDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / 'saves').mkdir()
        self.release = self.base / 'releases/plus-0123456789abcdef'
        self.source = self.release / 'BepInEx/vplus-data'
        self.source.mkdir(parents=True)
        self.target = self.base / 'saves/vplus-data'
        (self.source / 'North_mapPins.dat').write_bytes(b'old shared map pins')
        (self.source / 'North_mapPinsDeleted.dat').write_bytes(b'')

    def tearDown(self):
        self.tmp.cleanup()

    def need_symlinks(self):
        probe = self.base / 'symlink-probe'
        try:
            probe.symlink_to(self.base / 'saves', target_is_directory=True)
        except OSError:
            self.skipTest('Directory symlink permission is unavailable')
        probe.unlink()

    def test_migration_keeps_files_empty_tombstones_and_original_copy(self):
        self.need_symlinks()
        prepare_vplus_data(self.base, self.release)
        self.assertTrue(self.source.is_symlink())
        self.assertEqual(self.source.resolve(), self.target)
        self.assertEqual((self.target / 'North_mapPins.dat').read_bytes(), b'old shared map pins')
        self.assertEqual((self.target / 'North_mapPinsDeleted.dat').read_bytes(), b'')
        original = next(self.source.parent.glob('vplus-data.hearth-migrated-*'))
        self.assertEqual((original / 'North_mapPins.dat').read_bytes(), b'old shared map pins')
        prepare_vplus_data(self.base, self.release)  # Existing correct links are harmless.
        self.assertEqual(len(list(self.source.parent.glob('vplus-data.hearth-migrated-*'))), 1)

    def test_conflict_preserves_both_files_and_source_directory(self):
        self.target.mkdir()
        (self.target / 'North_mapPins.dat').write_bytes(b'new canonical pins')
        with self.assertRaisesRegex(ValueError, 'Конфликт данных V'):
            prepare_vplus_data(self.base, self.release)
        self.assertFalse(self.source.is_symlink())
        self.assertEqual((self.source / 'North_mapPins.dat').read_bytes(), b'old shared map pins')
        self.assertEqual((self.target / 'North_mapPins.dat').read_bytes(), b'new canonical pins')
        self.assertFalse((self.target / 'North_mapPinsDeleted.dat').exists())

    def test_same_existing_file_is_kept_and_missing_files_are_migrated(self):
        self.need_symlinks()
        self.target.mkdir()
        (self.target / 'North_mapPins.dat').write_bytes(b'old shared map pins')
        (self.target / 'Other_mapPins.dat').write_bytes(b'other world')
        prepare_vplus_data(self.base, self.release)
        self.assertEqual((self.target / 'Other_mapPins.dat').read_bytes(), b'other world')
        self.assertTrue((self.target / 'North_mapPinsDeleted.dat').exists())

    def test_failed_copy_keeps_original_and_does_not_publish_partial_file(self):
        with patch('vplus_data.shutil.copyfileobj', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                prepare_vplus_data(self.base, self.release)
        self.assertEqual((self.source / 'North_mapPins.dat').read_bytes(), b'old shared map pins')
        self.assertFalse(self.source.is_symlink())
        self.assertEqual(list(self.target.iterdir()), [])

    def test_failed_link_restores_original_directory(self):
        with patch.object(Path, 'symlink_to', side_effect=OSError('link denied')):
            with self.assertRaises(OSError):
                prepare_vplus_data(self.base, self.release)
        self.assertFalse(self.source.is_symlink())
        self.assertEqual((self.source / 'North_mapPins.dat').read_bytes(), b'old shared map pins')
        self.assertEqual((self.target / 'North_mapPins.dat').read_bytes(), b'old shared map pins')
        self.assertEqual(list(self.source.parent.glob('vplus-data.hearth-migrated-*')), [])

    def test_probe_files_are_not_copied_into_real_world_state(self):
        self.need_symlinks()
        (self.source / 'VersionProbe_mapPins.dat').write_bytes(b'probe pins')
        prepare_vplus_data(self.base, self.release, migrate=False)
        self.assertTrue(self.source.is_symlink())
        self.assertEqual(list(self.target.iterdir()), [])
        original = next(self.source.parent.glob('vplus-data.hearth-migrated-*'))
        self.assertEqual((original / 'VersionProbe_mapPins.dat').read_bytes(), b'probe pins')

    def test_symlinks_and_paths_outside_release_root_are_rejected(self):
        self.need_symlinks()
        with self.assertRaises(ValueError):
            prepare_vplus_data(self.base, self.base / 'saves')
        external = self.base / 'external'
        external.mkdir()
        (external / 'keep').write_bytes(b'keep')
        (self.source / 'linked').symlink_to(external / 'keep')
        with self.assertRaises(ValueError):
            prepare_vplus_data(self.base, self.release)
        (self.source / 'linked').unlink()
        (self.target / 'linked').symlink_to(external / 'keep')
        with self.assertRaises(ValueError):
            prepare_vplus_data(self.base, self.release)
        (self.target / 'linked').unlink()
        self.target.rmdir()
        self.target.symlink_to(external, target_is_directory=True)
        with self.assertRaises(ValueError):
            prepare_vplus_data(self.base, self.release)
        self.assertEqual((external / 'keep').read_bytes(), b'keep')

    def test_unexpected_source_subdirectory_is_preserved(self):
        (self.source / 'custom').mkdir()
        with self.assertRaises(ValueError):
            prepare_vplus_data(self.base, self.release)
        self.assertTrue((self.source / 'custom').is_dir())

    def test_backup_migrates_stopped_legacy_data_and_restore_recovers_it(self):
        self.need_symlinks()
        manager = server.Manager(self.base)
        try:
            manager.state['active'] = self.release.name
            server.atomic_json(self.release / 'hearth.json', {'mode': 'plus', 'game': '1.0.21', 'mod': '10.4.0.0'})
            manager.save_state()
            name = manager.backup()
            with tarfile.open(self.base / 'backups' / name) as archive:
                self.assertEqual(archive.extractfile('saves/vplus-data/North_mapPins.dat').read(), b'old shared map pins')
                self.assertEqual(archive.extractfile('saves/vplus-data/North_mapPinsDeleted.dat').read(), b'')
            (self.target / 'North_mapPins.dat').write_bytes(b'later pins')
            with patch.object(manager, 'start'), patch.object(manager, 'publish_client_mods'):
                manager.restore(name)
            self.assertEqual((self.target / 'North_mapPins.dat').read_bytes(), b'old shared map pins')
            self.assertEqual(self.source.resolve(), self.target)
        finally:
            for handler in manager.log.handlers[:]:
                handler.close()
                manager.log.removeHandler(handler)


if __name__ == '__main__':
    unittest.main()
