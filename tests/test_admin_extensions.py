"""Authenticated integration of moderation, recurring jobs and private health."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import server


class AdminExtensionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manager = server.Manager(Path(self.tmp.name))
        self.manager.panel.save({**self.manager.panel.load(), 'auth':server.password_hash('extension-admin-password')})
        self.handler = type('ExtensionHandler', (server.Handler,), {'manager':self.manager, 'sessions':{}})
        self.handler.attempts.clear()
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), self.handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        status, headers, result = self.request('POST', '/api/login', {'password':'extension-admin-password'}, {'X-Hearth':'1', 'Content-Type':'application/json'})
        self.assertEqual(status, 200)
        self.headers = {'Cookie':headers['Set-Cookie'].split(';')[0], 'X-Hearth':'1', 'Content-Type':'application/json', 'X-CSRF-Token':result['csrf']}

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        for handler in self.manager.log.handlers[:]:
            handler.close()
            self.manager.log.removeHandler(handler)
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        connection.request(method, path, json.dumps(body) if body is not None else None, headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), json.loads(response.read())
        connection.close()
        return result

    def test_timed_ban_profile_and_reason_are_private_and_persisted(self):
        sid = '76561198000000007'
        profile = {'action':'profile', 'steam_id':sid, 'alias':'Shield Bearer', 'notes':'Private moderator note'}
        self.assertEqual(self.request('POST', '/api/players', profile, self.headers)[0], 200)
        with patch.object(self.manager.operations, 'notify') as notify:
            body = {'action':'ban', 'steam_id':sid, 'reason':'Repeated griefing', 'duration_hours':2}
            status, _, result = self.request('POST', '/api/players', body, self.headers)
            self.assertEqual(status, 200)
            self.assertEqual(result['access']['timed_bans'][0]['reason'], body['reason'])
            self.assertGreater(result['access']['timed_bans'][0]['until'], time.time()+7100)
            self.assertIn(body['reason'], notify.call_args.args[1])
            self.assertNotIn(profile['notes'], notify.call_args.args[1])
        self.assertTrue((self.manager.base/'moderation.json').is_file())
        public = self.request('GET', '/api/public')[2]
        for secret in (sid, profile['alias'], profile['notes'], body['reason']):
            self.assertNotIn(secret, json.dumps(public))
        for key in ('health', 'player_access', 'routines'):
            self.assertNotIn(key, public)
        status, _, private = self.request('GET', '/api/status', headers=self.headers)
        self.assertEqual(status, 200)
        self.assertIn('health', private)
        self.assertEqual(private['player_access']['profiles'][sid]['notes'], profile['notes'])

    def test_routine_create_pause_remove_with_csrf_and_busy_protection(self):
        body = {'command':'routine_save', 'operation':'backup', 'frequency':'daily', 'weekdays':[],
                'time':'04:00', 'timezone':'UTC', 'enabled':True, 'max_wait_minutes':120}
        bad = {**self.headers, 'X-CSRF-Token':'wrong'}
        self.assertEqual(self.request('POST', '/api/operations', body, bad)[0], 403)
        with self.manager.lock:
            self.assertEqual(self.request('POST', '/api/operations', body, self.headers)[0], 400)
        status, _, result = self.request('POST', '/api/operations', body, self.headers)
        self.assertEqual(status, 200)
        rid = result['routines'][0]['id']
        self.assertTrue(result['upcoming'])
        status, _, result = self.request('POST', '/api/operations', {'command':'routine_toggle', 'id':rid, 'enabled':False}, self.headers)
        self.assertEqual(status, 200)
        self.assertFalse(result['routines'][0]['enabled'])
        self.assertEqual(result['upcoming'], [])
        status, _, result = self.request('POST', '/api/operations', {'command':'routine_remove', 'id':rid}, self.headers)
        self.assertEqual(status, 200)
        self.assertEqual(result['routines'], [])

    def test_health_stays_available_when_a2s_or_metrics_fail(self):
        self.manager.online = None
        status, _, private = self.request('GET', '/api/status', headers=self.headers)
        self.assertEqual(status, 200)
        self.assertIn('process', private['health'])
        self.assertFalse(private['health']['process']['running'])
        self.assertFalse(private['health']['a2s']['fresh'])
        self.assertEqual(self.request('GET', '/api/status')[0], 401)

    def test_expired_window_after_slow_a2s_prevents_disruption(self):
        self.manager.maintenance_wait_empty = True
        self.manager.maintenance_deadline = 1001
        fake = MagicMock()
        fake.info.return_value.player_count = 0
        with patch.object(self.manager, 'running', return_value=True), patch.dict(sys.modules, {'a2s':fake}), patch('server.time.time', side_effect=[1000,1002]):
            with self.assertRaisesRegex(ValueError, 'Окно обслуживания истекло'):
                self.manager.guard_maintenance()
        with patch.object(self.manager, 'stop') as stop, patch.object(self.manager, 'start') as start:
            with self.assertRaisesRegex(ValueError, 'Окно обслуживания истекло'):
                self.manager.execute('restart', {})
            stop.assert_not_called()
            start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
