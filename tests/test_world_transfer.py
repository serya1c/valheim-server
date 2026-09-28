import collections
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import server
import world_transfer as transfer
from configuration import default_world
from panel import password_hash


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'SERVER_PASSWORD':'destination-secret','WORLD_NAME':'North','SERVER_MODE':'vanilla'});self.env.start()
        self.manager=server.Manager(self.base)
        self.manager.panel.save({'auth':password_hash('test-admin-password'), 'backup_hours':6,'backup_keep':12,'cookie_secure':False})
        self.release=self.base/'releases/current';self.release.mkdir()
        self.manager.state['active']='current'
        self.set_mode('vanilla')
        self.folder=self.base/'saves/worlds_local';self.folder.mkdir()
        (self.folder/'North.db').write_bytes(b'world-database')
        (self.folder/'North.fwl').write_bytes(b'world-metadata')
        server.atomic_json(self.manager.config.path,self.manager.config.load())
        self.stop=patch.object(self.manager,'stop').start()
        self.start=patch.object(self.manager,'start').start()
        self.running=patch.object(self.manager,'running',return_value=False).start()

    def tearDown(self):
        patch.stopall();self.env.stop()
        for h in self.manager.log.handlers[:]:h.close();self.manager.log.removeHandler(h)
        self.temp.cleanup()

    def set_mode(self,mode):
        server.atomic_json(self.release/'hearth.json',{'game':'1.0.16','mod':'0.10.2.0' if mode=='plus' else None,'mode':mode})

    def export(self):
        transfer.export_world(self.manager)
        return next((self.base/'exports').glob('*.zip'))

    def stage(self,path):
        with path.open('rb') as f:return transfer.stage_import(self.manager,f,path.stat().st_size)

    def rewrite(self,path,edit):
        with zipfile.ZipFile(path) as z:files={n:z.read(n) for n in z.namelist()}
        edit(files)
        with zipfile.ZipFile(path,'w') as z:
            for n,b in files.items():z.writestr(n,b)

    def test_vanilla_roundtrip_preserves_host_credentials_and_other_world(self):
        path=self.export()
        with zipfile.ZipFile(path) as z:
            self.assertEqual(set(z.namelist()),{'manifest.json','world.db','world.fwl'})
            self.assertNotIn(b'destination-secret',z.read('manifest.json'))
        (self.folder/'North.db').write_bytes(b'replaced')
        (self.folder/'Other.db').write_bytes(b'other-world')
        (self.folder/'North.db.old').write_bytes(b'stale-world')
        before=self.manager.config.load();before['world_name']='Other';before['worlds']['Other']=default_world();before['landing']['title']='Destination'
        server.atomic_json(self.manager.config.path,before)
        preview=self.stage(path)
        self.assertEqual((self.folder/'North.db').read_bytes(),b'replaced')
        transfer.import_world(self.manager,preview['token'])
        after=self.manager.config.load()
        self.assertEqual(after['world_name'],'North')
        self.assertEqual(after['server']['password'],'destination-secret')
        self.assertEqual(after['landing']['title'],'Destination')
        self.assertEqual((self.folder/'Other.db').read_bytes(),b'other-world')
        self.assertFalse((self.folder/'North.db.old').exists())
        self.assertEqual((self.folder/'North.db').read_bytes(),b'world-database')
        self.assertTrue(list((self.base/'backups').glob('*-pre-import.tar.gz')))
        self.assertTrue(self.manager.panel.verify('test-admin-password'))
        self.start.assert_not_called()

    def test_plus_config_is_exact_and_target_filename_is_preserved(self):
        self.set_mode('plus')
        cfg=self.base/'config/valheim_plus.cfg';original=b'# original comment\n[Server]\nenabled = true\n'
        cfg.write_bytes(original)
        path=self.export();cfg.unlink()
        canonical=self.base/'config/org.bepinex.plugins.valheim_plus.cfg';canonical.write_bytes(b'[Server]\nenabled=false')
        preview=self.stage(path);transfer.import_world(self.manager,preview['token'])
        self.assertEqual(canonical.read_bytes(),original)
        self.assertFalse(cfg.exists())

    def test_plus_missing_config_fails_and_export_restarts_running_server(self):
        self.set_mode('plus');self.running.return_value=True
        with self.assertRaises(ValueError):self.export()
        self.start.assert_called_once()

    def test_missing_world_pair_does_not_export(self):
        (self.folder/'North.fwl').unlink()
        with self.assertRaises(ValueError):self.export()
        self.assertFalse(list((self.base/'exports').glob('*.zip')))

    def test_archive_paths_extra_files_and_checksum_rejected_before_stop(self):
        path=self.export();original=path.read_bytes();self.stop.reset_mock()
        for mutate in (lambda f:f.update({'../evil':b'no'}),lambda f:f.update({'world.db':b'tampered'}),lambda f:f.pop('world.fwl')):
            path.write_bytes(original);self.rewrite(path,mutate)
            with self.assertRaises(ValueError):self.stage(path)
        self.stop.assert_not_called()
        self.assertIsNone(self.manager.pending_import)
        self.assertFalse(list((self.base/'incoming').glob('*.zip')))

    def test_duplicate_symlink_and_oversize_entries_rejected(self):
        path=self.export()
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(path,'a') as z:
                info=zipfile.ZipInfo('valheim_plus.cfg');info.external_attr=0o120777<<16;z.writestr(info,b'other')
            with self.assertRaises(ValueError):transfer.read_package(path,Path(tmp))
        path.unlink();path=self.export()
        with patch.object(transfer,'MAX_EXPANDED',1),self.assertRaises(ValueError):self.stage(path)
        with zipfile.ZipFile(path,'a') as z:z.writestr('world.db',b'duplicate')
        with self.assertRaises(ValueError):self.stage(path)

    def test_mode_and_version_mismatch_rejected_and_rechecked(self):
        path=self.export();preview=self.stage(path)
        self.set_mode('plus')
        with self.assertRaises(ValueError):transfer.import_world(self.manager,preview['token'])
        with self.assertRaises(ValueError):self.stage(path)
        self.set_mode('vanilla')
        server.atomic_json(self.release/'hearth.json',{'mode':'vanilla','game':'1.0.15'})
        with self.assertRaises(ValueError):self.stage(path)

    def test_expired_token_and_truncated_upload_do_not_mutate_world(self):
        path=self.export();preview=self.stage(path);self.manager.pending_import['expires']=0
        with self.assertRaises(ValueError):transfer.import_world(self.manager,preview['token'])
        with self.assertRaises(ValueError):transfer.stage_import(self.manager,io.BytesIO(b'abc'),100)
        self.assertEqual((self.folder/'North.db').read_bytes(),b'world-database')

    def test_invalid_rules_and_missing_plus_config_rejected(self):
        path=self.export()
        def mutate(files):
            meta=json.loads(files['manifest.json']);meta['rules']['preset']='invented';files['manifest.json']=json.dumps(meta).encode()
        self.rewrite(path,mutate)
        with self.assertRaises(ValueError):self.stage(path)
        def plus(files):
            meta=json.loads(files['manifest.json']);meta['mode']='plus';meta['mod']='0.10.2.0';files['manifest.json']=json.dumps(meta).encode()
        self.rewrite(path,plus)
        with self.assertRaises(ValueError):self.stage(path)

    def test_write_failure_rolls_back_both_world_files(self):
        path=self.export();preview=self.stage(path)
        (self.folder/'North.db').write_bytes(b'old-db');(self.folder/'North.fwl').write_bytes(b'old-fwl')
        config=self.manager.config.path.read_bytes()
        real=transfer.atomic_text
        def fail_destination(path,content):
            if path==self.manager.config.path:raise OSError('disk full')
            return real(path,content)
        with patch.object(transfer,'atomic_text',side_effect=fail_destination),self.assertRaises(OSError):transfer.import_world(self.manager,preview['token'])
        self.assertEqual((self.folder/'North.db').read_bytes(),b'old-db')
        self.assertEqual((self.folder/'North.fwl').read_bytes(),b'old-fwl')
        self.assertEqual(self.manager.config.path.read_bytes(),config)

    def test_backup_failure_does_not_replace_world(self):
        path=self.export();preview=self.stage(path);(self.folder/'North.db').write_bytes(b'old-db')
        with patch.object(self.manager,'backup',side_effect=OSError('full')),self.assertRaises(OSError):transfer.import_world(self.manager,preview['token'])
        self.assertEqual((self.folder/'North.db').read_bytes(),b'old-db')

    def test_http_upload_requires_auth_csrf_and_serializes_operations(self):
        path=self.export();body=path.read_bytes()
        class Handler(server.Handler):
            sessions={'test-session':{'csrf':'test-csrf','expires':9999999999}}
            attempts=collections.deque(maxlen=100)
        Handler.manager=self.manager
        httpd=server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
        def request(method,url,headers=None,data=None):
            c=http.client.HTTPConnection('127.0.0.1',httpd.server_port,timeout=15);c.request(method,url,data,headers or {});r=c.getresponse();result=r.status,r.read();c.close();return result
        headers={'Content-Type':'application/zip','X-Hearth':'1','X-CSRF-Token':'test-csrf','Cookie':'session=test-session'}
        try:
            self.assertEqual(request('POST','/api/world-import',data=body)[0],403)
            self.assertEqual(request('POST','/api/world-import',{**headers,'X-CSRF-Token':'wrong'},body)[0],403)
            self.assertEqual(request('GET','/api/world-export/'+path.name)[0],401)
            status,download=request('GET','/api/world-export/'+path.name,headers)
            self.assertEqual((status,download),(200,body))
            with self.manager.lock:self.assertEqual(request('POST','/api/world-import',headers,body)[0],409)
            status,response=request('POST','/api/world-import',headers,body)
            self.assertEqual(status,200,response)
            self.assertEqual(json.loads(response)['world'],'North')
        finally:httpd.shutdown();httpd.server_close()
