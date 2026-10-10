import copy
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import time
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

    def test_client_bundle_limits_preserve_published_archive(self):
        self.add('Author-World')
        self.manager.install('Author-World')
        archive = self.manager.client_archive()
        original = archive.read_bytes()
        for limit, value in (('MAX_ARCHIVE', 64), ('MAX_CLIENT_FILES', 1)):
            with self.subTest(limit=limit), patch('mods.' + limit, value), self.assertRaisesRegex(ValueError, 'ограничения установщика'):
                self.manager.client_archive()
            self.assertEqual(archive.read_bytes(), original)



class HexiumTests(unittest.TestCase):
    """Second source: Thunderstore first, Hexium for missing or deprecated packages."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.manager = mods.ModManager(self.base)
        self.thunderstore, self.deprecated, self.hexium, self.downloads = {}, set(), {}, {}
        for target, effect in (('mods._json', self.fetch_json), ('mods._fetch', self.fetch),
                               ('mods._hexium_index', self.hexium_index)):
            patcher = patch(target, side_effect=effect)
            setattr(self, target.split('.')[1].strip('_') + '_mock', patcher.start())
            self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)

    def archive(self, ident, version, deps):
        name = ident.split('-', 1)[1]
        return zipped({name + '.dll': b'MZ-' + ident.encode() + version.encode()},
                      {'name': name, 'version_number': version, 'dependencies': list(deps)})

    def add_thunderstore(self, ident, version='1.0.0', deps=(), deprecated=False):
        namespace, name = ident.split('-', 1)
        url = f'https://thunderstore.io/package/download/{namespace}/{name}/{version}/'
        self.thunderstore.setdefault(ident, {})[version] = {
            'namespace': namespace, 'name': name, 'version_number': version, 'dependencies': list(deps),
            'download_url': url, 'description': 'Thunderstore copy', 'is_active': True}
        if deprecated:
            self.deprecated.add(ident)
        self.downloads[url] = self.archive(ident, version, deps)

    def add_hexium(self, ident, version='1.0.0', deps=(), deprecated=False, zip_deps=None):
        package = self.hexium.setdefault(ident.casefold(), {'full_name': ident, 'is_deprecated': deprecated, 'versions': []})
        url = f'https://cdn.hexium.gg/upload/{len(self.downloads)}/{version}.zip'
        package['versions'].insert(0, {'version_number': version, 'dependencies': list(deps), 'download_url': url,
                                       'description': 'Hexium copy', 'is_active': True})
        self.downloads[url] = self.archive(ident, version, deps if zip_deps is None else zip_deps)

    def fetch_json(self, url):
        parts = url.removeprefix(mods.API).strip('/').split('/')
        ident = '-'.join(parts[:2])
        releases = self.thunderstore.get(ident)
        if not releases or len(parts) == 3 and parts[2] not in releases:
            raise mods._Missing('Пакет мода не найден')
        if len(parts) == 3:
            return copy.deepcopy(releases[parts[2]])
        latest = max(releases, key=lambda value: tuple(map(int, value.split('.'))))
        return {'latest': copy.deepcopy(releases[latest]), 'is_deprecated': ident in self.deprecated,
                'community_listings': [{'community': 'valheim'}]}

    def fetch(self, url, limit=mods.MAX_ARCHIVE):
        return self.downloads[url]

    def hexium_index(self):
        return copy.deepcopy(self.hexium)

    def package(self, ident):
        return next(item for item in self.manager.view()['packages'] if item['id'] == ident)

    def test_live_thunderstore_package_wins_over_hexium(self):
        self.add_thunderstore('Author-World', '1.0.0')
        self.add_hexium('Author-World', '9.0.0')
        self.manager.install('Author-World')
        package = self.package('Author-World')
        self.assertEqual((package['source'], package['version']), ('thunderstore', '1.0.0'))
        self.hexium_index_mock.assert_not_called()

    def test_deprecated_thunderstore_package_moves_to_live_hexium_copy(self):
        self.add_thunderstore('Azumatt-AzuAreaRepair', '1.1.7', deprecated=True)
        self.add_hexium('Azumatt-AzuAreaRepair', '1.1.8', ['denikson-BepInExPack_Valheim-5.4.2351'])
        self.manager.install('https://thunderstore.io/c/valheim/p/Azumatt/AzuAreaRepair/', scope='client')
        package = self.package('Azumatt-AzuAreaRepair')
        self.assertEqual((package['source'], package['version']), ('hexium', '1.1.8'))
        self.assertEqual(package['source_url'], 'https://valheim.hexium.gg/mods/Azumatt/AzuAreaRepair')
        self.assertTrue(any(call.args[0].startswith('https://cdn.hexium.gg/') for call in self.fetch_mock.call_args_list))

    def test_deprecated_package_without_hexium_copy_still_installs_from_thunderstore(self):
        self.add_thunderstore('Azumatt-ImFRIENDLY_DAMMIT', '1.1.9', deprecated=True)
        self.manager.install('Azumatt-ImFRIENDLY_DAMMIT-1.1.9')
        self.assertEqual(self.package('Azumatt-ImFRIENDLY_DAMMIT')['source'], 'thunderstore')
        self.manager.install('Azumatt-ImFRIENDLY_DAMMIT')
        self.assertEqual(self.package('Azumatt-ImFRIENDLY_DAMMIT')['version'], '1.1.9')

    def test_hexium_link_and_hexium_only_dependency(self):
        self.add_hexium('Smoothbrain-ServerSync', '2.0.0')
        self.add_hexium('Smoothbrain-Farming', '2.3.0', ['Smoothbrain-ServerSync-2.0.0'])
        self.add_thunderstore('Smoothbrain-Farming', '2.2.2')  # live, but the link pins Hexium
        self.manager.install('https://valheim.hexium.gg/mods/Smoothbrain/Farming', scope='both')
        self.assertEqual({item['id']: (item['source'], item['version']) for item in self.manager.view()['packages']},
                         {'Smoothbrain-Farming': ('hexium', '2.3.0'), 'Smoothbrain-ServerSync': ('hexium', '2.0.0')})
        self.manager = mods.ModManager(self.base)  # persisted state with the new source loads
        self.assertEqual(self.package('Smoothbrain-Farming')['source'], 'hexium')

    def test_hexium_package_updates_from_hexium(self):
        self.add_hexium('Azumatt-AzuAreaRepair', '1.1.8')
        self.manager.install('https://valheim.hexium.gg/mods/Azumatt/AzuAreaRepair')
        self.add_hexium('Azumatt-AzuAreaRepair', '1.1.9')
        self.add_thunderstore('Azumatt-AzuAreaRepair', '1.1.7')
        self.manager.update('Azumatt-AzuAreaRepair')
        self.assertEqual((self.package('Azumatt-AzuAreaRepair')['source'], self.package('Azumatt-AzuAreaRepair')['version']),
                         ('hexium', '1.1.9'))

    def test_hexium_manifest_may_omit_only_the_loader_dependency(self):
        loader = 'denikson-BepInExPack_Valheim-5.4.2351'
        self.add_hexium('shudnal-ConditionalConfigSync', '1.0.5', [loader], zip_deps=[])
        self.add_hexium('dreich-linkedstations', '1.0.0', [loader, 'shudnal-ConditionalConfigSync-1.0.5'],
                        zip_deps=['shudnal-ConditionalConfigSync-1.0.5'])
        self.manager.install('https://valheim.hexium.gg/mods/dreich/linkedstations')
        self.assertEqual({item['id']: item['source'] for item in self.manager.view()['packages']},
                         {'dreich-linkedstations': 'hexium', 'shudnal-ConditionalConfigSync': 'hexium'})

    def test_hexium_manifest_mismatch_beyond_loader_is_rejected_and_nothing_changes(self):
        loader = 'denikson-BepInExPack_Valheim-5.4.2351'
        self.add_hexium('Author-Base', '1.0.0')
        self.add_hexium('Author-World', '1.0.0', [loader, 'Author-Base-1.0.0'], zip_deps=[])
        self.add_hexium('Author-Other', '1.0.0', [loader], zip_deps=['denikson-BepInExPack_Valheim-5.4.2200'])
        before = self.manager.view()
        for link in ('https://valheim.hexium.gg/mods/Author/World', 'https://valheim.hexium.gg/mods/Author/Other'):
            with self.subTest(link=link), self.assertRaisesRegex(ValueError, 'Манифест ZIP не совпадает'):
                self.manager.install(link)
        self.assertEqual(self.manager.view(), before)
        self.assertEqual(list((self.manager.root / 'packages').iterdir()), [])

    def test_thunderstore_manifest_must_still_list_the_loader(self):
        self.add_thunderstore('Author-World', '1.0.0', ['denikson-BepInExPack_Valheim-5.4.2351'])
        self.downloads['https://thunderstore.io/package/download/Author/World/1.0.0/'] = self.archive('Author-World', '1.0.0', [])
        with self.assertRaisesRegex(ValueError, 'Манифест ZIP не совпадает'):
            self.manager.install('Author-World')

    def test_exact_pin_missing_everywhere_is_reported_and_nothing_changes(self):
        self.add_thunderstore('Author-World', '1.0.0')
        before = self.manager.view()
        with self.assertRaisesRegex(ValueError, 'не найден'):
            self.manager.install('Author-World-2.0.0')
        self.assertEqual(self.manager.view(), before)

    def test_loader_is_never_taken_from_hexium(self):
        self.add_hexium(mods.LOADER_ID, '5.4.2351')
        with self.assertRaises(mods._Missing):
            self.manager._prepare_loader()
        self.hexium_index_mock.assert_not_called()

    def test_hexium_link_formats_and_download_hosts(self):
        self.assertEqual(mods._reference('https://valheim.hexium.gg/mods/Azumatt/AzuAreaRepair'), ('Azumatt-AzuAreaRepair', None))
        self.assertEqual(mods._source_hint('https://valheim.hexium.gg/mods/Azumatt/AzuAreaRepair'), 'hexium')
        self.assertIsNone(mods._source_hint('https://thunderstore.io/c/valheim/p/Azumatt/AzuAreaRepair/'))
        for bad in ('http://valheim.hexium.gg/mods/A/B', 'https://valheim.hexium.gg/other/A/B',
                    'https://evil.hexium.gg.example/mods/A/B', 'https://valheim.hexium.gg:8443/mods/A/B'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                mods._reference(bad)
        self.assertEqual(mods._network_url('https://cdn.hexium.gg/upload/247/1.1.8.zip'), 'https://cdn.hexium.gg/upload/247/1.1.8.zip')
        for bad in ('http://cdn.hexium.gg/x.zip', 'https://cdn.hexium.gg.evil.example/x.zip', 'https://user@cdn.hexium.gg/x.zip'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                mods._network_url(bad)


class HexiumIndexTests(unittest.TestCase):
    def setUp(self):
        mods._HEXIUM_CACHE.update(at=0.0, index=None)
        self.addCleanup(mods._HEXIUM_CACHE.update, at=0.0, index=None)

    def test_listing_is_compacted_cached_and_validated(self):
        listing = [{'full_name': 'Azumatt-AzuAreaRepair', 'is_deprecated': False, 'owner': 'Azumatt', 'categories': ['x'],
                    'versions': [{'version_number': '1.1.8', 'dependencies': [], 'download_url': 'https://cdn.hexium.gg/upload/247/1.1.8.zip',
                                  'description': 'Repair', 'is_active': True, 'downloads': 5, 'icon': 'https://cdn.hexium.gg/i.png'}]},
                   'junk', {'name': 'no full name'}]
        with patch('mods._fetch', return_value=json.dumps(listing).encode()) as fetch:
            index = mods._hexium_index()
            self.assertIs(mods._hexium_index(), index)
            fetch.assert_called_once_with(mods.HEXIUM_INDEX, mods.MAX_INDEX)
        self.assertEqual(list(index), ['azumatt-azuarearepair'])
        self.assertEqual(set(index['azumatt-azuarearepair']['versions'][0]),
                         {'version_number', 'dependencies', 'download_url', 'description', 'is_active'})
        metadata = mods._hexium_metadata('Azumatt-AzuAreaRepair')
        self.assertEqual((metadata['version_number'], metadata['source']), ('1.1.8', 'hexium'))
        with self.assertRaises(mods._Missing):
            mods._hexium_metadata('Azumatt-AzuAreaRepair', '9.9.9')
        with patch('mods.time.monotonic', return_value=time_after(mods.HEXIUM_TTL)), \
                patch('mods._fetch', return_value=b'[]') as fetch:
            self.assertEqual(mods._hexium_index(), {})
            fetch.assert_called_once()

    def test_invalid_listing_is_rejected_and_not_cached(self):
        for payload in (b'{"not": "a list"}', b'<!DOCTYPE html>'):
            with self.subTest(payload=payload), patch('mods._fetch', return_value=payload), \
                    self.assertRaisesRegex(ValueError, 'Hexium'):
                mods._hexium_index()
        self.assertIsNone(mods._HEXIUM_CACHE['index'])


def time_after(seconds):
    return time.monotonic() + seconds + 1


if __name__ == '__main__':
    unittest.main()
