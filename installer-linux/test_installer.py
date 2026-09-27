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


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.game=self.root/'Игры/Valheim';self.game.mkdir(parents=True)
        (self.game/'valheim.exe').write_bytes(fake_pe());(self.game/'valheim_Data').mkdir()
        self.stage=self.root/'stage';self.stage.mkdir()
        self.data=Path('/fixture/WindowsClient.zip').read_bytes()
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

if __name__=='__main__':unittest.main()
