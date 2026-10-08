import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import loki_installer as m


def fake_pe():
    data=bytearray(150);data[:2]=b'MZ';struct.pack_into('<I',data,0x3c,100);data[100:106]=b'PE\0\0\x64\x86';return data


class EndpointTests(unittest.TestCase):
    def test_custom_server_origin(self):
        self.assertEqual(m.server_endpoint('https://north.example.org/'),'https://north.example.org/api/public')
    def test_invalid_origins(self):
        for url in ['http://north.example.org','https://u:p@north.example.org','https://north.example.org/path','https://north.example.org?x=1','https://north.example.org:8443']:
            with self.subTest(url=url),self.assertRaises(ValueError):m.server_endpoint(url)
    def test_vanilla_refused(self):
        with patch.object(m,'fetch',return_value=b'{"mode":"vanilla","game":"1.0.16","mod":null}'),self.assertRaisesRegex(ValueError,'ванильный'):
            m.server_version()
    def test_api_redirect_cannot_change_host(self):
        import urllib.error
        from unittest.mock import MagicMock
        opener=MagicMock()
        opener.open.side_effect=urllib.error.HTTPError('https://north.example.org/api/public',302,'Redirect',{'Location':'https://other.example.org'},None)
        with patch.object(m,'SERVER','https://north.example.org/api/public'),patch.object(m.urllib.request,'build_opener',return_value=opener),self.assertRaisesRegex(ValueError,'источник'):
            m.fetch(m.SERVER)
        self.assertEqual(opener.open.call_count,1)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.game=self.root/'Игры/Valheim';self.game.mkdir(parents=True)
        (self.game/'valheim.exe').write_bytes(fake_pe());(self.game/'valheim_Data').mkdir()
        self.stage=self.root/'stage';self.stage.mkdir()
        fixture=Path(os.environ.get('LOKI_CLIENT_FIXTURE','/fixture/WindowsClient.zip'))
        if not fixture.exists(): fixture=Path(__file__).resolve().parents[2]/'WindowsClient.zip'
        self.data=fixture.read_bytes()
        self.files=m.extract(self.data,self.stage)
    def tearDown(self):self.temp.cleanup()
    def apply(self,**kw):return m.install(self.game,self.stage,self.files,'0.10.2.0',log=lambda x:None,**kw)
    def test_official_archive(self):
        self.assertEqual(hashlib.sha256(self.data).hexdigest(),m.KNOWN_HASH)
        self.assertTrue(m.REQUIRED.issubset(self.files))
    def test_find_steam_flatpak_and_link(self):
        home=self.root/'home';steam=home/'.var/app/com.valvesoftware.Steam/.local/share/Steam'
        (steam/'steamapps').mkdir(parents=True)
        library=self.root/'Второй диск/SteamLibrary';(library/'steamapps/common').mkdir(parents=True)
        (library/'steamapps/common/Valheim').symlink_to(self.game,target_is_directory=True)
        (library/'steamapps/appmanifest_892970.acf').write_text('"AppState" { "appid" "892970" "installdir" "Valheim" }')
        (steam/'steamapps/libraryfolders.vdf').write_text('"libraryfolders" { "0" { "path" '+json.dumps(str(library),ensure_ascii=False)+' } }')
        alias=home/'.steam';alias.mkdir();(alias/'steam').symlink_to(steam,target_is_directory=True)
        self.assertEqual(m.find_games(home),[self.game])
    def test_vdf_old_and_comments(self):
        self.assertEqual(m.vdf('// hello\n"libraryfolders" {"0" "/mnt/Games"}')['libraryfolders']['0'],'/mnt/Games')
        with self.assertRaises(ValueError):m.vdf('x { y')
    def test_manifest_escape(self):
        home=self.root/'home';steam=home/'.local/share/Steam/steamapps';steam.mkdir(parents=True)
        (steam/'appmanifest_892970.acf').write_text('"AppState" {"appid" "892970" "installdir" "../Valheim"}')
        self.assertEqual(m.find_games(home),[])
    def test_native_linux_rejected(self):
        (self.game/'valheim.exe').unlink();(self.game/'valheim.x86_64').touch()
        with self.assertRaises(ValueError):m.validate_game(self.game)
    def test_case_conflict(self):
        (self.game/'bepinex').mkdir()
        with self.assertRaises(ValueError):self.apply()
    def test_internal_symlink(self):
        (self.game/'BepInEx').symlink_to(self.stage/'BepInEx',target_is_directory=True)
        with self.assertRaises(ValueError):self.apply()
    def test_unsafe_paths(self):
        for name in ['../outside','/tmp/test','BepInEx/../../escape','BepInEx/CON.txt','winhttp.dll:stream']:
            with self.subTest(name=name),self.assertRaises(ValueError):m.safe(self.game,name)
    def test_unsafe_zip(self):
        for name in ['BepInEx/../../escape','valheim.exe']:
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w') as z:z.writestr(name,'bad')
            with self.assertRaises(ValueError):m.extract(stream.getvalue(),self.stage)
    def test_zip_duplicate_and_symlink(self):
        for symlink in [False,True]:
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w') as z:
                if symlink:
                    i=zipfile.ZipInfo('BepInEx/link');i.external_attr=0o120777<<16;z.writestr(i,'/tmp')
                else:z.writestr('winhttp.dll',b'x');z.writestr('WINHTTP.DLL',b'x')
            target=self.root/str(symlink);target.mkdir()
            with self.assertRaises(ValueError):m.extract(stream.getvalue(),target)
    def test_install_restore_preserves_configuration(self):
        (self.game/'winhttp.dll').write_bytes(b'old');(self.game/'BepInEx/config').mkdir(parents=True)
        (self.game/'BepInEx/config/BepInEx.cfg').write_text('my config')
        (self.game/'BepInEx/other.txt').write_text('other')
        backup=self.apply()
        self.assertEqual((backup/'original/winhttp.dll').read_bytes(),b'old')
        self.assertEqual((self.game/'BepInEx/config/BepInEx.cfg').read_text(),'my config')
        m.restore(self.game)
        self.assertEqual((self.game/'winhttp.dll').read_bytes(),b'old')
        self.assertFalse((self.game/'BepInEx/plugins/ValheimPlus.dll').exists())
        self.assertEqual((self.game/'BepInEx/other.txt').read_text(),'other')
    def test_failed_copy_rolls_back(self):
        (self.game/'winhttp.dll').write_text('old')
        def fail(index):
            if index==4:raise OSError('injected failure')
        with self.assertRaises(OSError):self.apply(before_copy=fail)
        self.assertEqual((self.game/'winhttp.dll').read_text(),'old')
        self.assertFalse((self.game/'BepInEx/plugins/ValheimPlus.dll').exists())
        self.assertEqual(m.read_journal(m.latest(self.game))['state'],'restored')
    def test_restore_preserves_later_user_changes(self):
        self.apply();(self.game/'winhttp.dll').write_text('changed')
        with self.assertRaises(ValueError):m.restore(self.game)
        self.assertEqual((self.game/'winhttp.dll').read_text(),'changed')
    def test_interrupted_install_requires_restore(self):
        backup=self.apply();j=m.read_journal(backup);j['state']='installing';m.save_journal(backup,j)
        with self.assertRaises(ValueError):self.apply()
        m.restore(self.game);self.assertFalse((self.game/'winhttp.dll').exists())
    def test_reinstall_restore_previous_mod(self):
        self.apply();before=m.digest(self.game/'winhttp.dll');self.apply();m.restore(self.game)
        self.assertEqual(m.digest(self.game/'winhttp.dll'),before)
    def test_lock(self):
        with m.lock(self.game),self.assertRaises(RuntimeError):self.apply()
    def test_running_game(self):
        proc=self.root/'proc/123';proc.mkdir(parents=True);(proc/'comm').write_text('valheim.exe\n')
        with self.assertRaises(RuntimeError):m.game_closed(proc.parent)
    def test_wrong_server_and_release(self):
        with patch.object(m,'fetch',return_value=b'{"game":null,"mod":null}'),self.assertRaises(ValueError):m.server_version()
        with patch.object(m,'fetch',return_value=b'{"game":"1.0.15","mod":"0.10.2.0"}'):
            self.assertEqual(m.server_version(),('1.0.15','0.10.2.0'))
        with self.assertRaises(ValueError):m.release_asset({'tag_name':'latest'},'0.10.2.0')
    def test_checksum_failure(self):
        release={'tag_name':'0.10.2.0','draft':False,'prerelease':False,'assets':[{'name':'WindowsClient.zip','browser_download_url':'https://github.com/Grantapher/ValheimPlus/releases/download/0.10.2.0/WindowsClient.zip'}]}
        with patch.object(m,'fetch',side_effect=[json.dumps(release).encode(),b'bad']),self.assertRaises(ValueError):m.download('0.10.2.0')
    def test_reject_missing_future_hash(self):
        release={'tag_name':'0.11.0.0','draft':False,'prerelease':False,'assets':[{'name':'WindowsClient.zip','browser_download_url':'https://github.com/Grantapher/ValheimPlus/releases/download/0.11.0.0/WindowsClient.zip'}]}
        with self.assertRaises(ValueError):m.release_asset(release,'0.11.0.0')
    def test_bepinex6_conflict(self):
        (self.game/'BepInEx/core').mkdir(parents=True);(self.game/'BepInEx/core/BepInEx.Core.dll').touch()
        with self.assertRaises(ValueError):self.apply()

    def archive(self, entries):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive:
            for name,content in entries.items(): archive.writestr(name,content)
        return stream.getvalue()

    def bundle(self, data, kind='full'):
        return {'url':'/downloads/Hearth-Client-Mods.zip','sha256':hashlib.sha256(data).hexdigest(),
                'revision':'a'*64,'size':len(data),'kind':kind,'packages':[{'id':'test-addon','name':'Test addon','version':'1.0.0'}]}

    def full(self):
        entries={'winhttp.dll':fake_pe(),'doorstop_config.ini':b'config','BepInEx/core/BepInEx.dll':fake_pe(),
                 'BepInEx/plugins/HearthMods/test/addon.dll':b'addon','hearth-mods.json':b'{"schema":1}'}
        return self.archive(entries)

    def test_generic_bundle_needs_no_vplus_or_github(self):
        data=self.full();bundle=self.bundle(data)
        manifest=m.parse_server({'mode':'modded','game':'1.0.15','mod':None,'client_mods':bundle})
        stage=self.root/'generic';stage.mkdir()
        with patch.object(m,'download',side_effect=AssertionError('GitHub must not be used')),patch.object(m,'download_bundle',return_value=data):
            files=m.prepare(manifest,stage)
        self.assertIn('BepInEx/core/BepInEx.dll',files)
        self.assertNotIn('BepInEx/plugins/ValheimPlus.dll',files)
        self.assertNotIn('hearth-mods.json',files)
        with patch.object(m,'server_manifest',return_value=manifest):
            m.install_selected(self.game,stage,files,manifest,log=lambda _:None)
        self.assertTrue((self.game/'BepInEx/plugins/HearthMods/test/addon.dll').is_file())
        m.restore(self.game)
        self.assertFalse((self.game/'BepInEx/plugins/HearthMods/test/addon.dll').exists())

    def test_plus_base_and_overlay_are_combined_without_core_replacement(self):
        extra=self.archive({'BepInEx/plugins/HearthMods/test/addon.dll':b'addon','hearth-mods.json':b'{"schema":1}'})
        manifest=m.parse_server({'mode':'plus','game':'1.0.15','mod':'0.10.2.0','client_mods':self.bundle(extra,'overlay')})
        stage=self.root/'combined';stage.mkdir()
        with patch.object(m,'download',return_value=self.data) as official,patch.object(m,'download_bundle',return_value=extra):
            files=m.prepare(manifest,stage)
        official.assert_called_once_with('0.10.2.0')
        self.assertIn('BepInEx/plugins/ValheimPlus.dll',files)
        self.assertIn('BepInEx/plugins/HearthMods/test/addon.dll',files)
        for name in ['winhttp.dll','BepInEx/core/BepInEx.dll','BepInEx/config/private.cfg']:
            target=self.root/name.replace('/','-');target.mkdir()
            with self.subTest(name=name),self.assertRaises(ValueError):m.extract(self.archive({name:b'bad'}),target,overlay=True)

    def test_invalid_bundle_metadata_and_size_or_hash_are_rejected(self):
        data=self.full();bundle=self.bundle(data)
        for field,value in [('url','https://other.example.org/mods.zip'),('url','//other.example.org/mods.zip'),('size',True),('size',0),('size',129*1024*1024),('sha256','bad'),('revision','bad'),('kind','overlay')]:
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                m.parse_server({'mode':'modded','game':'1.0.15','client_mods':{**bundle,field:value}})
        with self.assertRaises(ValueError):m.parse_server({'mode':'modded','game':'1.0.15','client_mods':None})
        for downloaded in [b'bad',b'x'*len(data)]:
            with patch.object(m,'fetch',return_value=downloaded),self.assertRaises(ValueError):m.download_bundle(bundle)

    def test_bundle_revision_change_prevents_install(self):
        manifest=m.parse_server({'mode':'modded','game':'1.0.15','client_mods':self.bundle(self.full())})
        changed={**manifest,'client_mods':{**manifest['client_mods'],'revision':'b'*64}}
        with patch.object(m,'server_manifest',return_value=changed),patch.object(m,'install') as install,self.assertRaises(ValueError):
            m.install_selected(self.game,self.stage,self.files,manifest)
        install.assert_not_called()
        self.assertFalse((self.game/'.loki-installer-linux').exists())

    def test_bundle_redirect_cannot_change_server_origin(self):
        import urllib.error
        from unittest.mock import MagicMock
        opener=MagicMock()
        opener.open.side_effect=urllib.error.HTTPError('https://north.example.org/downloads/Hearth-Client-Mods.zip',302,'Redirect',{'Location':'https://other.example.org/mods.zip'},None)
        with patch.object(m,'SERVER','https://north.example.org/api/public'),patch.object(m.urllib.request,'build_opener',return_value=opener),self.assertRaisesRegex(ValueError,'источник'):
            m.fetch('https://north.example.org/downloads/Hearth-Client-Mods.zip',1024,from_server=True)
        self.assertEqual(opener.open.call_count,1)

    def test_stale_owned_files_are_removed_and_restore_recovers_them(self):
        old='BepInEx/plugins/HearthMods/test/old.dll';changed='BepInEx/plugins/HearthMods/test/changed.dll'
        for name in [old,changed]:
            path=self.stage/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'original addon')
        m.install(self.game,self.stage,self.files+[old,changed],'0.10.2.0',log=lambda _:None)
        user=self.game/'BepInEx/plugins/HearthMods/user.dll';user.write_bytes(b'unknown user mod')
        (self.game/changed).write_bytes(b'user-edited addon')
        self.apply()
        self.assertFalse((self.game/old).exists())
        self.assertEqual((self.game/changed).read_bytes(),b'user-edited addon')
        self.assertEqual(user.read_bytes(),b'unknown user mod')
        m.restore(self.game)
        self.assertEqual((self.game/old).read_bytes(),b'original addon')
        self.assertEqual((self.game/changed).read_bytes(),b'user-edited addon')

    def test_generic_transition_removes_only_owned_vplus_and_restore_recovers_it(self):
        self.apply()
        stage=self.root/'generic';stage.mkdir();files=m.extract(self.full(),stage,require_plus=False)
        m.install(self.game,stage,files,'BepInEx',generic=True,log=lambda _:None)
        self.assertFalse((self.game/'BepInEx/plugins/ValheimPlus.dll').exists())
        m.restore(self.game)
        self.assertTrue((self.game/'BepInEx/plugins/ValheimPlus.dll').exists())
        (self.game/'BepInEx/plugins/ValheimPlus.dll').write_bytes(b'private VPlus')
        with self.assertRaisesRegex(ValueError,'пользовательский'):
            m.install(self.game,stage,files,'BepInEx',generic=True,log=lambda _:None)
        self.assertEqual((self.game/'BepInEx/plugins/ValheimPlus.dll').read_bytes(),b'private VPlus')

if __name__=='__main__':unittest.main()
