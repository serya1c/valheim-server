import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from launcher_downloads import launcher_downloads


class LauncherDownloadsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        (self.folder / 'Hearth-Launcher.version').write_text('1.0.0\n')

    def tearDown(self):
        self.temp.cleanup()

    def asset(self, name):
        payload = b'launcher fixture'
        (self.folder / name).write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        (self.folder / (name + '.sha256')).write_text(digest + '  ' + name + '\n')
        return digest

    def test_missing_binaries_hide_downloads(self):
        self.assertIsNone(launcher_downloads(self.folder))

    def test_ready_platforms_have_matching_public_metadata(self):
        digest = self.asset('Hearth-Launcher.exe')
        result = launcher_downloads(self.folder)
        self.assertEqual(result['version'], '1.0.0')
        self.assertEqual(result['windows']['sha256'], digest)
        self.assertEqual(result['windows']['size'], len(b'launcher fixture'))
        self.assertEqual(result['windows']['url'], '/downloads/Hearth-Launcher.exe')
        self.assertNotIn('linux', result)
        self.asset('Hearth-Launcher-Linux.tar.gz')
        self.assertIn('linux', launcher_downloads(self.folder))

    def test_invalid_checksums_and_version_are_hidden(self):
        self.asset('Hearth-Launcher.exe')
        checksum = self.folder / 'Hearth-Launcher.exe.sha256'
        checksum.write_text('a' * 64 + '  unrelated.exe\n')
        self.assertIsNone(launcher_downloads(self.folder))
        checksum.write_text('bad  Hearth-Launcher.exe\n')
        self.assertIsNone(launcher_downloads(self.folder))
        self.asset('Hearth-Launcher.exe')
        (self.folder / 'Hearth-Launcher.version').write_text('1.0.0<script>')
        self.assertIsNone(launcher_downloads(self.folder))

    def test_empty_binary_is_not_advertised(self):
        self.asset('Hearth-Launcher.exe')
        (self.folder / 'Hearth-Launcher.exe').write_bytes(b'')
        self.assertIsNone(launcher_downloads(self.folder))


if __name__ == '__main__':
    unittest.main()
