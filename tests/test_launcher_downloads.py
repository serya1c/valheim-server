import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from launcher_downloads import NAMES, launcher_downloads


class LauncherDownloadsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        (self.folder / 'Hearth-Launcher.version').write_text('1.1.0\n')

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

    def test_setup_and_portable_downloads_have_matching_public_metadata(self):
        for platform, name in NAMES.items():
            digest = self.asset(name)
            result = launcher_downloads(self.folder)
            self.assertEqual(result['version'], '1.1.0')
            self.assertEqual(result[platform]['sha256'], digest)
            self.assertEqual(result[platform]['size'], len(b'launcher fixture'))
            self.assertEqual(result[platform]['url'], '/downloads/' + name)
            self.assertEqual(result[platform]['checksum_url'], '/downloads/' + name + '.sha256')
        self.assertEqual(set(launcher_downloads(self.folder)), {'version', *NAMES})

    def test_portable_builds_do_not_masquerade_as_installers(self):
        self.asset('Hearth-Launcher.exe')
        result = launcher_downloads(self.folder)
        self.assertIn('windows_portable', result)
        self.assertNotIn('windows', result)
        self.assertNotIn('linux', result)

    def test_invalid_checksums_and_version_are_hidden(self):
        self.asset('Hearth-Launcher-Setup.exe')
        checksum = self.folder / 'Hearth-Launcher-Setup.exe.sha256'
        checksum.write_text('a' * 64 + '  unrelated.exe\n')
        self.assertIsNone(launcher_downloads(self.folder))
        checksum.write_text('bad  Hearth-Launcher-Setup.exe\n')
        self.assertIsNone(launcher_downloads(self.folder))
        self.asset('Hearth-Launcher-Setup.exe')
        (self.folder / 'Hearth-Launcher.version').write_text('1.1.0<script>')
        self.assertIsNone(launcher_downloads(self.folder))

    def test_empty_or_oversized_installer_is_not_advertised(self):
        for name in ('Hearth-Launcher-Setup.exe', 'Hearth-Launcher-Install-Linux.sh'):
            self.asset(name)
            (self.folder / name).write_bytes(b'')
            self.assertIsNone(launcher_downloads(self.folder))
            with (self.folder / name).open('wb') as stream:
                stream.truncate(100 * 1024 * 1024 + 1)
            self.assertIsNone(launcher_downloads(self.folder))


if __name__ == '__main__':
    unittest.main()
