import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from operations import Operations, NoRedirect
import server

class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.manager=MagicMock()
        self.manager.base=Path(self.tmp.name)
        self.manager.config.load.return_value={'server':{'name':'Test server'},'landing':{'site_url':'https://example.org'}}
        self.manager.running.return_value=True
        self.manager.busy=False
        self.manager.online=None
        self.manager.maintenance_wait_empty=False
        self.ops=Operations(self.manager)
    def tearDown(self):
        self.ops.messages.join()
        self.tmp.cleanup()
    def schedule(self,wait=True):
        self.ops.schedule({'operation':'restart','at':time.time(),'wait_empty':wait})
    def test_unknown_stale_and_populated_online_never_runs(self):
        self.schedule()
        for online in [None,{'count':0,'at':time.time()-60},{'count':2,'at':time.time()}]:
            self.manager.online=online;self.ops.tick()
        self.manager.submit.assert_not_called()
    def test_empty_minute_and_recheck_before_execution(self):
        self.schedule();self.manager.online={'count':0,'at':time.time()}
        self.ops.tick();self.manager.submit.assert_not_called()
        self.ops.empty_since=time.time()-61;self.ops.tick()
        self.manager.submit.assert_called_once_with('maintenance')
        self.manager.online={'count':1,'at':time.time()}
        self.ops.run_pending();self.manager.execute.assert_not_called()
        self.assertEqual(self.ops.view()['maintenance']['state'],'pending')
    def test_player_activity_resets_empty_minute_while_busy(self):
        self.schedule();self.ops.empty_since=time.time()-61
        self.manager.busy=True;self.manager.online={'count':1,'at':time.time()}
        self.ops.tick();self.assertIsNone(self.ops.empty_since)
        self.manager.busy=False;self.manager.online={'count':0,'at':time.time()}
        self.ops.tick();self.manager.submit.assert_not_called()

    def test_due_time_cancel_and_restart_persistence(self):
        self.ops.schedule({'operation':'backup','at':time.time()+3600,'wait_empty':False})
        self.ops.tick();self.manager.submit.assert_not_called()
        resumed=Operations(self.manager);self.assertEqual(resumed.view()['maintenance']['state'],'pending')
        resumed.cancel();resumed.tick();self.manager.submit.assert_not_called()
    def test_run_once_and_interrupted_task_is_not_replayed(self):
        self.schedule(False);self.ops.run_pending();self.ops.run_pending()
        self.manager.execute.assert_called_once_with('restart',{})
        self.assertEqual(self.ops.view()['maintenance']['state'],'done')
        self.ops.data['maintenance']['state']='running';self.ops.save()
        resumed=Operations(self.manager);resumed.tick()
        self.assertEqual(resumed.view()['maintenance']['state'],'interrupted')
        self.manager.submit.assert_not_called()
    def test_failed_task_is_not_retried_and_guard_resets(self):
        self.schedule(True);self.manager.running.return_value=False
        self.manager.execute.side_effect=ValueError('failed')
        with self.assertRaises(ValueError):self.ops.run_pending()
        self.assertEqual(self.ops.view()['maintenance']['state'],'error')
        self.assertFalse(self.manager.maintenance_wait_empty)
    def test_success_and_guard_failure_clear_wait_flag(self):
        self.schedule(True);self.manager.running.return_value=False
        self.ops.run_pending()
        self.assertFalse(self.manager.maintenance_wait_empty)
        self.schedule(True);self.manager.guard_maintenance.side_effect=ValueError('players returned')
        with self.assertRaises(ValueError):self.ops.run_pending()
        self.assertFalse(self.manager.maintenance_wait_empty)
        self.assertEqual(self.ops.view()['maintenance']['state'],'error')

    def test_write_failure_does_not_change_pending_task(self):
        with patch.object(self.ops,'save',side_effect=OSError('full')):
            with self.assertRaises(OSError):self.schedule()
        self.assertIsNone(self.ops.view()['maintenance'])
        self.schedule()
        with patch.object(self.ops,'save',side_effect=OSError('full')):
            with self.assertRaises(OSError):self.ops.cancel()
            self.manager.running.return_value=False
            with self.assertRaises(OSError):self.ops.run_pending()
        self.assertEqual(self.ops.view()['maintenance']['state'],'pending')
        self.manager.execute.assert_not_called()

    def test_invalid_schedule_and_duplicate_rejected(self):
        for value in [float('nan'),float('inf'),0,time.time()+31*86400]:
            with self.assertRaises(ValueError):self.ops.schedule({'operation':'restart','at':value,'wait_empty':True})
        self.schedule()
        with self.assertRaises(ValueError):self.schedule()
    def test_webhook_secret_preserved_removed_and_not_in_view(self):
        url='https://discord.com/api/webhooks/123/'+'a'*40
        self.ops.configure_discord({'url':url,'events':['error']})
        self.assertNotIn(url,json.dumps(self.ops.view()))
        self.ops.configure_discord({'url':'','events':['server']})
        self.assertEqual(self.ops.data['discord']['url'],url)
        self.ops.configure_discord({'remove':True,'events':[]})
        self.assertFalse(self.ops.view()['discord']['configured'])
    def test_webhook_domain_and_redirect_restrictions(self):
        for url in ['http://discord.com/api/webhooks/123/'+'a'*40,'https://evil.test/hook','https://discord.com.evil.test/hook','https://discord.com/api/webhooks/123/'+'a'*40+'?url=x']:
            with self.assertRaises(ValueError):self.ops.configure_discord({'url':url,'events':[]})
        self.assertIsNone(NoRedirect().redirect_request(None,None,None,None,None,None))
    def test_notifications_opt_in_no_mentions_dedup_and_errors_redacted(self):
        with patch('operations.request') as send:
            self.ops.notify('error','message');send.assert_not_called()
            self.ops.configure_discord({'url':'https://discord.com/api/webhooks/123/'+'a'*40,'events':['error']})
            self.ops.notify('server','ignored');self.ops.notify('error','failure');self.ops.notify('error','failure')
            self.ops.messages.join();self.assertEqual(send.call_count,1)
            self.assertEqual(send.call_args.args[1]['allowed_mentions'],{'parse':[]})
            send.side_effect=OSError('secret URL must not escape')
            self.ops.notify('error','another failure');self.ops.messages.join()
            self.assertNotIn('secret URL',self.ops.delivery)
    def test_removed_webhook_discards_queued_messages(self):
        url='https://discord.com/api/webhooks/123/'+'a'*40
        self.ops.configure_discord({'url':url,'events':['error']})
        self.ops.messages.put((url,'queued before removal'))
        self.ops.configure_discord({'remove':True,'events':[]})
        with patch('operations.request') as send:
            self.ops.deliver()
            send.assert_not_called()
        self.ops.messages.join()

    def test_release_comparison_cache_and_invalid_tag(self):
        self.ops.release['current']='1.2.2'
        with patch('operations.request',return_value=json.dumps({'tag_name':'v1.3.0'}).encode()) as fetch:
            self.ops.check_release();self.ops.check_release();self.assertEqual(fetch.call_count,1)
        self.assertTrue(self.ops.view()['release']['available'])
        self.ops.release['checked']=None
        with patch('operations.request',return_value=b'{"tag_name":"bad"}'):
            self.ops.check_release()
        self.assertTrue(self.ops.view()['release']['error'])
    def test_update_guard_rechecks_live_player_count(self):
        fake=MagicMock();fake.maintenance_wait_empty=True;fake.maintenance_deadline=None;fake.running.return_value=True
        with patch.dict(sys.modules,{'a2s':MagicMock()}) as modules:
            modules['a2s'].info.return_value.player_count=1
            with self.assertRaises(ValueError):server.Manager.guard_maintenance(fake)
            modules['a2s'].info.return_value.player_count=0
            server.Manager.guard_maintenance(fake)
            fake.maintenance_deadline=time.time()-1
            with self.assertRaisesRegex(ValueError,'Окно обслуживания истекло'):
                server.Manager.guard_maintenance(fake)
