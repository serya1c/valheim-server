import collections
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import server
from configuration import default_world


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'PANEL_PASSWORD':'', 'SERVER_PASSWORD':'', 'REQUIRE_PUBLIC_LISTING':'0'})
        self.env.start()
        self.manager = server.Manager(self.base)
        class Handler(server.Handler):
            sessions = {}
            attempts = collections.deque(maxlen=100)
        Handler.manager = self.manager
        self.handler = Handler
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.submission = patch.object(self.manager, 'submit')
        self.submit = self.submission.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.submission.stop()
        self.env.stop()
        for h in self.manager.log.handlers[:]:
            h.close()
            self.manager.log.removeHandler(h)
        self.temp.cleanup()

    def request(self, method, path, data=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.http.server_port)
        c.request(method, path, json.dumps(data) if data is not None else None, headers or {})
        r = c.getresponse()
        result = r.status, dict(r.getheaders()), r.read()
        c.close()
        return result

    def body(self):
        return {'panel_password':'new-admin-password-123',
            'panel':{'backup_hours':6,'backup_keep':12,'cookie_secure':False},
            'server':{'name':'New world','password':'game-password','mode':'vanilla','public':False,'add_site':False},
            'world':{'name':'NewWorld','rules':default_world()},
            'landing':{'title':'New world','site_url':'http://localhost:8080','address':'example.org:2456','community_url':''}}

    def headers(self):
        data = json.loads(self.request('GET','/api/setup')[2])
        return {'Content-Type':'application/json','X-Hearth':'1','X-Setup-Token':data['csrf']}

    def test_unconfigured_serves_wizard_and_never_exposes_management(self):
        status, headers, body = self.request('GET','/')
        self.assertEqual(status,200)
        self.assertIn(b'/setup.js',body)
        self.assertEqual(headers['X-Robots-Tag'],'noindex, nofollow')
        self.assertEqual(self.request('GET','/api/status')[0],409)
        self.assertEqual(self.request('GET','/api/public')[0],409)
        self.assertEqual(self.request('GET','/health')[0],200)
        self.submit.assert_not_called()

    def test_public_host_and_proxy_cannot_claim_setup(self):
        for headers in [{'Host':'public.example.org'}, {'Host':'localhost:8080','X-Forwarded-For':'127.0.0.1'}, {'Host':'localhost','Forwarded':'for=127.0.0.1'}]:
            with self.subTest(headers=headers):
                self.assertEqual(self.request('GET','/api/setup',headers=headers)[0],503)
                supplied={**self.headers(),**headers}
                self.assertEqual(self.request('POST','/api/setup',self.body(),supplied)[0],403)
        self.assertFalse(self.manager.panel.configured)

    def test_setup_requires_one_time_token(self):
        headers=self.headers();headers['X-Setup-Token']='wrong'
        self.assertEqual(self.request('POST','/api/setup',self.body(),headers)[0],403)
        self.assertFalse(self.manager.panel.configured)

    def test_setup_persists_hash_and_blocks_second_claim(self):
        headers=self.headers()
        self.assertEqual(self.request('POST','/api/setup',self.body(),headers)[0],201)
        self.submit.assert_called_once_with('install')
        self.assertEqual(self.manager.config.load()['server']['mode'],'vanilla')
        self.assertNotIn('new-admin-password-123',self.manager.panel.path.read_text())
        self.assertTrue(server.Panel(self.base).verify('new-admin-password-123'))
        self.assertFalse(server.Panel(self.base).verify('wrong'))
        self.assertEqual(self.request('GET','/api/setup')[0],409)
        self.assertEqual(self.request('POST','/api/setup',self.body(),headers)[0],409)
        self.assertIn(b'/landing.js',self.request('GET','/')[2])
        login_headers={'Content-Type':'application/json','X-Hearth':'1'}
        status,h,raw=self.request('POST','/api/login',{'password':'new-admin-password-123'},login_headers)
        self.assertEqual(status,200)
        authenticated={'Cookie':h['Set-Cookie']}
        view=json.loads(self.request('GET','/api/config',headers=authenticated)[2])
        self.assertNotIn('auth',view['panel'])
        archive=self.manager.backup()
        with tarfile.open(self.base/'backups'/archive) as tar:
            self.assertNotIn('panel.json',tar.getnames())

    def test_invalid_settings_leave_no_partial_setup(self):
        for mutate in [lambda d:d.update(panel_password='short'),lambda d:d['server'].update(mode='unknown'),lambda d:d['world'].update(name='../bad'),lambda d:d['landing'].update(site_url='javascript:bad'),lambda d:d['panel'].update(backup_hours=-1),lambda d:d['panel'].update(cookie_secure=True)]:
            d=self.body();mutate(d)
            self.assertEqual(self.request('POST','/api/setup',d,self.headers())[0],400)
            self.assertFalse(self.manager.panel.configured)
            self.assertFalse(self.manager.config.path.exists())
        self.submit.assert_not_called()

    def test_write_failure_allows_retry(self):
        with patch.object(self.manager.panel,'save',side_effect=OSError('disk full')):
            self.assertEqual(self.request('POST','/api/setup',self.body(),self.headers())[0],500)
        self.assertFalse(self.manager.config.path.exists())
        self.assertFalse(self.manager.panel.configured)
        self.assertEqual(self.request('POST','/api/setup',self.body(),self.headers())[0],201)

    def test_concurrent_claim_only_commits_once(self):
        headers=self.headers()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.request('POST','/api/setup',self.body(),headers)[0],range(2)))
        self.assertEqual(results.count(201),1)
        self.assertTrue(all(code in (201,400,409) for code in results))
        self.submit.assert_called_once()

    def test_existing_world_is_preserved_and_started(self):
        settings=self.manager.config.load()
        settings['server']['password']='existing-game-password'
        settings['world_name']='SavedWorld'
        settings['worlds']['SavedWorld']=default_world()
        server.atomic_json(self.manager.config.path,settings)
        (self.base/'saves/world.db').write_bytes(b'existing-world')
        release=self.base/'releases/existing';release.mkdir()
        server.atomic_json(release/'hearth.json',{'game':'1.0.16','mod':None,'mode':'vanilla'})
        self.manager.state['active']='existing'
        data=self.body();data['server']['password']='';data['world']['name']='SavedWorld'
        self.assertEqual(self.request('POST','/api/setup',data,self.headers())[0],201)
        self.submit.assert_called_once_with('start')
        self.assertEqual((self.base/'saves/world.db').read_bytes(),b'existing-world')
        self.assertEqual(self.manager.config.load()['server']['password'],'existing-game-password')
        self.assertEqual(len(list((self.base/'backups').glob('*-pre-setup.tar.gz'))),1)

    def test_main_waits_for_setup_without_starting_game(self):
        manager=MagicMock()
        manager.panel.configured=False
        with patch('server.Manager',return_value=manager),patch('server.ThreadingHTTPServer'),patch('server.threading.Thread'),patch('server.signal.signal'),patch('server.os.umask'):
            server.main()
        manager.submit.assert_not_called()

    def test_panel_settings_do_not_stop_game_and_password_needs_current(self):
        self.manager.complete_setup(self.body())
        values={**self.manager.panel.view(),'password':'replacement-admin-password','current_password':'wrong'}
        data={'scope':'panel','restart':False,'panel_revision':self.manager.panel.revision(),'values':values}
        with patch.object(self.manager,'stop') as stop:
            with self.assertRaises(ValueError):self.manager.configure(data)
            self.assertTrue(self.manager.panel.verify('new-admin-password-123'))
            values['current_password']='new-admin-password-123'
            self.manager.configure(data)
            stop.assert_not_called()
        self.assertTrue(self.manager.panel.verify('replacement-admin-password'))
