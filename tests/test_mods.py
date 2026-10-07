import copy
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import mods


def zipped(files, manifest=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        if manifest is not None:
            archive.writestr('manifest.json', json.dumps(manifest))
        for name, value in (files.items() if isinstance(files, dict) else files):
            archive.writestr(name, value)
    return stream.getvalue()


class ModTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.manager = mods.ModManager(self.base)
        self.metadata, self.downloads, self.latest = {}, {}, {}
        self.json_patch = patch('mods._json', side_effect=self.fetch_json)
        self.fetch_patch = patch('mods._fetch', side_effect=self.fetch)
        self.json_mock = self.json_patch.start()
        self.fetch_mock = self.fetch_patch.start()
        self.addCleanup(self.json_patch.stop)
        self.addCleanup(self.fetch_patch.stop)
        self.addCleanup(self.temp.cleanup)

    def add(self, ident, version='1.0.0', deps=(), files=None):
        namespace, name = ident.split('-', 1)
        url = f'https://thunderstore.io/package/download/{namespace}/{name}/{version}/'
        record = {'namespace': namespace, 'name': name, 'version_number': version,
                  'dependencies': list(deps), 'download_url': url, 'description': 'A plugin', 'is_active': True}
        self.metadata[(ident, version)] = record
        self.latest[ident] = version
        manifest = {'name': name, 'version_number': version, 'dependencies': list(deps)}
        self.downloads[url] = zipped(files or {name + '.dll': b'MZ-fixture-' + version.encode()}, manifest)
        return record

    def fetch_json(self, url):
        parts = url.removeprefix(mods.API).strip('/').split('/')
        ident = '-'.join(parts[:2])
        if len(parts) == 2:
            return {'latest': copy.deepcopy(self.metadata[(ident, self.latest[ident])]), 'community_listings': [{'community': 'valheim'}]}
        return copy.deepcopy(self.metadata[(ident, parts[2])])

    def fetch(self, url, limit=mods.MAX_ARCHIVE):
        return self.downloads[url]

    def versions(self):
        return {item['id']: item['version'] for item in self.manager.view()['packages']}

    def upload(self, files, name='Local mod', manifest=None):
        source = self.base / 'upload.zip'
        source.write_bytes(zipped(files, manifest))
        return self.manager.upload(source, name)

    def test_exact_dependencies_persist_and_cannot_be_disabled_or_removed(self):
        self.add('Author-Library', '1.2.0')
        self.add('Author-World', deps=['Author-Library-1.2.0', 'denikson-BepInExPack_Valheim-5.4.2333'])
        self.manager.install('https://thunderstore.io/c/valheim/p/Author/World/', scope='both')
        self.assertEqual(self.versions(), {'Author-Library': '1.2.0', 'Author-World': '1.0.0'})
        self.manager = mods.ModManager(self.base)
        for operation in (lambda: self.manager.remove('Author-Library'), lambda: self.manager.set_enabled('Author-Library', False)):
            with self.assertRaisesRegex(ValueError, 'Author-Library-1.2.0'):
                operation()
        self.manager.set_enabled('Author-World', False)
        self.manager.set_enabled('Author-Library', False)
        with self.assertRaises(ValueError):
            self.manager.set_enabled('Author-World', True)

    def test_parent_update_upgrades_unshared_dependency_atomically(self):
        self.add('Author-Library')
        self.add('Author-World', deps=['Author-Library-1.0.0'])
        self.manager.install('Author-World')
        self.add('Author-Library', '2.0.0')
        self.add('Author-World', '2.0.0', ['Author-Library-2.0.0'])
        self.manager.update('Author-World')
        self.assertEqual(self.versions(), {'Author-Library': '2.0.0', 'Author-World': '2.0.0'})
        self.assertEqual(len(list((self.manager.root / 'packages').iterdir())), 2)

    def test_dependency_upgrade_preserves_independently_enabled_runtime_scope(self):
        self.add('Author-Library')
        self.add('Author-World', deps=['Author-Library-1.0.0'])
        self.manager.install('https://valheim.thunderstore.io/package/Author/Library/', scope='both')
        self.manager.install('Author-World', scope='server')
        self.add('Author-Library', '2.0.0')
        self.add('Author-World', '2.0.0', ['Author-Library-2.0.0'])
        self.manager.update('Author-World')
        dependency = next(package for package in self.manager.view()['packages'] if package['id'] == 'Author-Library')
        self.assertEqual(dependency['version'], '2.0.0')
        self.assertEqual(dependency['scope'], 'both')

    def test_shared_dependency_pin_prevents_partial_parent_update(self):
        self.add('Author-Library')
        self.add('Author-World', deps=['Author-Library-1.0.0'])
        self.add('Other-Weather', deps=['Author-Library-1.0.0'])
        self.manager.install('Author-World')
        self.manager.install('Other-Weather')
        before = self.manager.view()
        old_manifest = self.manager.manifest.read_bytes()
        self.add('Author-Library', '2.0.0')
        self.add('Author-World', '2.0.0', ['Author-Library-2.0.0'])
        with self.assertRaisesRegex(ValueError, 'Author-Library-1.0.0'):
            self.manager.update('Author-World')
        self.assertEqual(self.manager.view(), before)
        self.assertEqual(self.manager.manifest.read_bytes(), old_manifest)
        self.assertEqual(len(list((self.manager.root / 'packages').iterdir())), 3)

    def test_two_incompatible_pins_in_new_dependency_graph_are_rejected(self):
        self.add('Author-Library')
        self.add('Author-Library', '2.0.0')
        self.add('Author-First', deps=['Author-Library-1.0.0'])
        self.add('Author-Second', deps=['Author-Library-2.0.0'])
        self.add('Author-World', deps=['Author-First-1.0.0', 'Author-Second-1.0.0'])
        with self.assertRaisesRegex(ValueError, 'Конфликт версий'):
            self.manager.install('Author-World')
        self.assertEqual(self.manager.view()['packages'], [])
        self.assertEqual(list((self.manager.root / 'packages').iterdir()), [])

    def test_scope_expands_dependency_and_exports_only_client_packages(self):
        self.add('Author-Library')
        self.add('Author-World', deps=['Author-Library-1.0.0'])
        self.add('Author-Server', files={'Server.dll': b'MZ', 'BepInEx/config/server.cfg': b'password=secret'})
        self.manager.install('Author-Library', scope='server')
        self.manager.install('Author-World', scope='both')
        self.manager.install('Author-Server', scope='server')
        packages = {item['id']: item for item in self.manager.view()['packages']}
        self.assertEqual(packages['Author-Library']['scope'], 'both')
        with zipfile.ZipFile(self.manager.client_archive()) as archive:
            names = archive.namelist()
            self.assertTrue(any('/Author-World/' in name for name in names))
            self.assertFalse(any('/Author-Server/' in name or name.endswith('.cfg') for name in names))
            public = json.loads(archive.read('hearth-mods.json'))
            self.assertNotIn('storage', json.dumps(public))
        release = self.base / 'release'
        release.mkdir()
        plus = release / 'BepInEx/plugins/ValheimPlus.dll'
        plus.parent.mkdir(parents=True)
        plus.write_bytes(b'untouched')
        self.manager.materialize(release)
        self.assertTrue((plus.parent / 'HearthMods/Author-Server/Server.dll').is_file())
        self.assertEqual(plus.read_bytes(), b'untouched')
        self.manager.set_enabled('Author-Server', False)
        self.manager.materialize(release)
        self.assertFalse((plus.parent / 'HearthMods/Author-Server').exists())
        self.assertEqual(plus.read_bytes(), b'untouched')

    def test_disabled_parent_update_keeps_new_dependency_disabled(self):
        self.add('Author-World')
        self.manager.install('Author-World')
        self.manager.set_enabled('Author-World', False)
        self.add('Author-Library')
        self.add('Author-World', '2.0.0', ['Author-Library-1.0.0'])
        self.manager.update('Author-World')
        self.assertTrue(all(not item['enabled'] for item in self.manager.view()['packages']))
        self.assertIsNone(self.manager.client_archive())

    def test_failed_manifest_replace_preserves_current_data_and_cleans_staging(self):
        self.add('Author-World')
        self.manager.install('Author-World')
        before = self.manager.view()
        self.add('Other-Weather')
        original = Path.replace
        def replace(source, target):
            if target == self.manager.manifest:
                raise OSError('simulated disk error')
            return original(source, target)
        with patch.object(Path, 'replace', replace), self.assertRaises(OSError):
            self.manager.install('Other-Weather')
        self.assertEqual(self.manager.view(), before)
        self.assertEqual(len(list((self.manager.root / 'packages').iterdir())), 1)
        self.assertEqual(mods.ModManager(self.base).view(), before)

    def test_upload_never_exports_scripts_configs_or_package_metadata(self):
        self.upload({'BepInEx/plugins/Extra/Extra.dll': b'MZ', 'BepInEx/plugins/Extra/data.json': b'{"asset":1}',
                     'BepInEx/plugins/Extra/icon.png': b'asset icon',
                     'BepInEx/config/Extra.cfg': b'password=secret', 'BepInEx/plugins/Extra/private.cfg': b'secret',
                     'run.exe': b'MZ', 'install.ps1': b'exit', 'README.md': b'readme'})
        with zipfile.ZipFile(self.manager.client_archive()) as archive:
            names = archive.namelist()
            self.assertTrue(any(name.endswith('/Extra/Extra.dll') for name in names))
            self.assertTrue(any(name.endswith('/Extra/data.json') for name in names))
            self.assertTrue(any(name.endswith('/Extra/icon.png') for name in names))
            self.assertFalse(any(name.endswith(('.cfg', '.exe', '.ps1', '.md')) for name in names))
            self.assertNotIn(b'secret', b''.join(archive.read(name) for name in names))

    def test_zip_paths_and_case_collisions_are_rejected_before_publication(self):
        bad = [('../outside.dll', b'MZ'), ('/outside.dll', b'MZ'),
               ('C:/outside.dll', b'MZ'), ('AUX.dll', b'MZ'), ('bad?.dll', b'MZ'), ('bad./x.dll', b'MZ')]
        for entry in bad:
            with self.subTest(path=entry[0]), self.assertRaises(ValueError):
                self.upload([('Good.dll', b'MZ'), entry])
        source = self.base / 'raw-path.zip'
        source.write_bytes(zipped({'dir/../bad.dll': b'MZ'}).replace(b'dir/../bad.dll', b'dir\\..\\bad.dll'))
        with self.assertRaises(ValueError):
            self.manager.upload(source, 'Raw paths')
        for files in ([('Good.dll', b'MZ'), ('GOOD.dll', b'MZ')],
                      [('Dir/X.dll', b'MZ'), ('dir/Y.dll', b'MZ')],
                      [('file', b'asset'), ('file/x.dll', b'MZ')],
                      [('plugins/Dir/X.dll', b'MZ'), ('BepInEx/plugins/dir/Y.dll', b'MZ')]):
            with self.subTest(files=files), self.assertRaises(ValueError):
                self.upload(files)
        self.assertEqual(self.manager.view()['packages'], [])
        self.assertEqual(list((self.manager.root / 'packages').iterdir()), [])

    def test_windows_zip_separators_are_normalized_for_thunderstore_packages(self):
        source = self.base / 'windows-path.zip'
        source.write_bytes(zipped({'plugins/Good.dll': b'MZ'}).replace(b'plugins/Good.dll', b'plugins\\Good.dll'))
        self.manager.upload(source, 'Windows paths')
        with zipfile.ZipFile(self.manager.client_archive()) as archive:
            self.assertTrue(any(name.endswith('/Good.dll') for name in archive.namelist()))
            self.assertFalse(any('\\' in name for name in archive.namelist()))

    def test_symlink_zip_and_native_patcher_packages_are_rejected(self):
        link = zipfile.ZipInfo('linked.dll')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for files in ([('Good.dll', b'MZ'), (link, b'../../somewhere')],
                      {'Good.dll': b'MZ', 'BepInEx/patchers/Patch.dll': b'MZ'},
                      {'Good.dll': b'MZ', 'native.so': b'ELF'},
                      {'Good.dll': b'MZ', 'ValheimPlus.dll': b'MZ'}):
            with self.subTest(files=files), self.assertRaises(ValueError):
                self.upload(files)
        self.assertEqual(self.manager.view()['packages'], [])

    def test_same_assembly_conflicts_only_when_runtime_scopes_overlap(self):
        self.add('Author-One', files={'Common.dll': b'MZ-one'})
        self.add('Other-Two', files={'common.DLL': b'MZ-two'})
        self.manager.install('Author-One', scope='server')
        with self.assertRaisesRegex(ValueError, 'Конфликт DLL'):
            self.manager.install('Other-Two', scope='both')
        self.manager.install('Other-Two', scope='client')
        self.assertEqual(len(self.manager.view()['packages']), 2)

    def test_external_plus_exact_version_and_candidate_mapping(self):
        self.add('Author-World', deps=['Grantapher-ValheimPlus-0.10.2.0', 'denikson-BepInExPack_Valheim-5.4.2333'])
        with self.assertRaisesRegex(ValueError, 'Valheim Plus'):
            self.manager.install('Author-World')
        self.manager.external_versions = lambda: {'ValheimPlus': '0.10.2.0'}
        self.manager.install('Author-World')
        self.assertEqual(list(self.versions()), ['Author-World'])
        self.assertTrue(self.manager.validate_external({'ValheimPlus': '0.10.2.0'}))
        for external in ({}, {'ValheimPlus': '0.10.3.0'}):
            with self.assertRaisesRegex(ValueError, 'Valheim Plus'):
                self.manager.validate_external(external)
        self.assertEqual(self.fetch_mock.call_count, 2)  # only plugin, never V+/loader archives

    def loader(self, version='5.4.2351'):
        self.add(mods.LOADER_ID, version, files={
            'BepInExPack_Valheim/BepInEx/core/BepInEx.Preloader.dll': b'MZ-preloader',
            'BepInExPack_Valheim/BepInEx/core/BepInEx.dll': b'MZ-core',
            'BepInExPack_Valheim/doorstop_libs/libdoorstop_x64.so': b'ELF',
            'BepInExPack_Valheim/doorstop_libs/libdoorstop_x64.dylib': b'ignored mac',
            'BepInExPack_Valheim/winhttp.dll': b'MZ-win',
            'BepInExPack_Valheim/doorstop_config.ini': b'enabled=true',
            'BepInExPack_Valheim/BepInEx/config/BepInEx.cfg': b'server/private=true',
            'BepInExPack_Valheim/start_server_bepinex.sh': b'never execute',
        })

    def test_loader_linux_materialization_and_cached_windows_bundle(self):
        self.loader()
        release = self.base / 'release'
        release.mkdir()
        self.assertEqual(self.manager.ensure_loader(release)['version'], '5.4.2351')
        self.assertTrue((release / 'doorstop_libs/libdoorstop_x64.so').exists())
        self.assertFalse((release / 'winhttp.dll').exists())
        self.assertFalse((release / 'BepInEx/config/BepInEx.cfg').exists())
        before = self.fetch_mock.call_count
        with zipfile.ZipFile(self.manager.client_archive(include_loader=True)) as archive:
            names = archive.namelist()
            self.assertIn('winhttp.dll', names)
            self.assertIn('doorstop_config.ini', names)
            self.assertIn('BepInEx/core/BepInEx.Preloader.dll', names)
            self.assertFalse(any(name.endswith(('.so', '.sh', '.cfg', '.dylib')) for name in names))
            self.assertEqual(json.loads(archive.read('hearth-mods.json'))['kind'], 'full')
        self.assertEqual(self.fetch_mock.call_count, before)
        self.loader('5.4.2400')
        self.assertEqual(self.manager.ensure_loader(release)['version'], '5.4.2351')
        self.assertEqual(self.manager.ensure_loader(release, refresh=True)['version'], '5.4.2400')

    def test_checksum_failure_preserves_existing_materialized_plugins(self):
        self.add('Author-World')
        self.manager.install('Author-World')
        release = self.base / 'release'
        release.mkdir()
        self.manager.materialize(release)
        old = release / 'BepInEx/plugins/HearthMods/Author-World/World.dll'
        before = old.read_bytes()
        package = self.manager.state['packages'][0]
        stored = self.manager.root / 'packages' / package['storage'] / package['files'][0]['path']
        stored.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'повреждены|сумма'):
            self.manager.materialize(release)
        self.assertEqual(old.read_bytes(), before)

    def test_invalid_persistent_manifest_is_rejected(self):
        self.add('Author-World')
        self.manager.install('Author-World')
        state = json.loads(self.manager.manifest.read_text())
        state['packages'][0]['files'][0]['path'] = '../outside.dll'
        self.manager.manifest.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'манифест'):
            mods.ModManager(self.base)

    def test_network_sources_and_declared_size_limits(self):
        for source in ('https://evil.test/c/valheim/p/A/B/', 'http://thunderstore.io/package/A/B/',
                       'https://thunderstore.io/package/A/B/?download=1', 'A-B->=1.0.0'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.manager.install(source)
        for url in ('http://thunderstore.io/file.zip', 'https://thunderstore.io.evil.test/file.zip',
                    'https://user:secret@thunderstore.io/file.zip', 'https://127.0.0.1/file.zip'):
            with self.assertRaises(ValueError):
                mods._network_url(url)
        with patch('mods.MAX_FILE', 8), self.assertRaises(ValueError):
            self.upload({'TooBig.dll': b'MZ' * 20})


if __name__ == '__main__':
    unittest.main()
