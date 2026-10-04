"""Recurrence, player-aware deadlines and restart persistence."""
from datetime import datetime, timezone
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from operations import Operations, next_occurrence, DEADLINE_ERROR

def stamp(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()

class RecurringTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.manager=MagicMock()
        self.manager.base=Path(self.tmp.name)
        self.manager.running.return_value=False
        self.manager.busy=False
        self.manager.online=None
        self.manager.config.load.return_value={'server':{'name':'Test'},'landing':{'site_url':'https://example.org'}}
        self.now=stamp('2026-10-05T00:00:00')
        self.clock=patch('operations.time.time',side_effect=lambda:self.now)
        self.clock.start()
        self.ops=Operations(self.manager)

    def tearDown(self):
        self.ops.messages.join()
        self.clock.stop()
        self.tmp.cleanup()

    def create(self,**overrides):
        values={'operation':'restart','frequency':'daily','weekdays':[],'time':'01:00','timezone':'UTC','enabled':True,'max_wait_minutes':120}
        values.update(overrides)
        self.ops.save_routine(values)
        return self.ops.view()['routines'][-1]

    def test_timezone_weekdays_and_seven_day_preview(self):
        daily=self.create(time='08:00',timezone='Asia/Krasnoyarsk')
        weekly=self.create(frequency='weekly',weekdays=[1,4],time='08:00',timezone='Asia/Krasnoyarsk')
        self.assertEqual(daily['next_at'],self.now+3600)
        self.assertEqual(weekly['next_at'],self.now+86400+3600)
        preview=self.ops.view()['upcoming']
        self.assertEqual(len(preview),9)
        self.assertEqual(preview[0]['timezone'],'Asia/Krasnoyarsk')
        self.assertTrue(all(t['deadline']-t['at']==7200 for t in preview))

    def test_dst_missing_time_skipped_and_ambiguous_time_only_once(self):
        routine={'frequency':'daily','weekdays':[],'time':'02:30','timezone':'America/New_York'}
        self.assertEqual(next_occurrence(routine,stamp('2026-03-08T05:00:00')),stamp('2026-03-09T06:30:00'))
        routine['time']='01:30'
        first=next_occurrence(routine,stamp('2026-11-01T04:00:00'))
        self.assertEqual(first,stamp('2026-11-01T05:30:00'))
        self.assertEqual(next_occurrence(routine,first+1),stamp('2026-11-02T06:30:00'))

    def test_validation_and_failed_save_preserve_existing_schedules(self):
        for changes in [{'timezone':'../bad'},{'frequency':'weekly','weekdays':[]},{'weekdays':[True]},{'time':'25:00'},{'max_wait_minutes':1},{'max_wait_minutes':1441},{'enabled':1}]:
            with self.assertRaises(ValueError):self.create(**changes)
        self.create()
        before=copy.deepcopy(self.ops.data)
        with patch.object(self.ops,'save',side_effect=OSError('full')):
            with self.assertRaises(OSError):self.create(operation='stop')
        self.assertEqual(self.ops.data,before)

    def test_simultaneous_schedules_run_once_sequentially_and_backup_is_rotated(self):
        self.create(operation='backup')
        self.create(operation='stop')
        self.now+=3600
        self.ops.tick()
        self.assertEqual(len(self.ops.data['recurring_queue']),1)
        self.ops.run_pending()
        self.ops.tick()
        self.ops.run_pending()
        self.assertEqual(self.manager.execute.call_count,2)
        self.assertCountEqual([call.args[0] for call in self.manager.execute.call_args_list],['scheduled','stop'])
        self.assertEqual([t['state'] for t in self.ops.view()['history']],['done','done'])
        self.ops.tick();self.ops.run_pending()
        self.assertEqual(self.manager.execute.call_count,2)

    def test_busy_or_populated_server_expires_without_execution(self):
        self.create(max_wait_minutes=2)
        self.now+=3600
        self.manager.running.return_value=True
        self.manager.online={'count':1,'at':self.now}
        self.manager.busy=True
        self.ops.tick()
        self.now+=121
        self.manager.online={'count':0,'at':self.now}
        self.manager.busy=False
        self.ops.tick();self.ops.run_pending()
        self.manager.execute.assert_not_called()
        self.assertEqual(self.ops.view()['maintenance']['state'],'skipped')
        self.assertEqual(self.ops.view()['history'][0]['reason'],'deadline')

    def test_player_activity_during_busy_resets_required_empty_minute(self):
        self.create()
        self.now+=3600
        self.manager.running.return_value=True
        self.manager.online={'count':0,'at':self.now}
        self.ops.tick()
        self.now+=30;self.manager.busy=True;self.manager.online={'count':2,'at':self.now}
        self.ops.tick()
        self.now+=40;self.manager.busy=False;self.manager.online={'count':0,'at':self.now}
        self.ops.tick();self.manager.submit.assert_not_called()
        self.now+=61;self.manager.online={'count':0,'at':self.now}
        self.ops.tick();self.ops.run_pending()
        self.manager.execute.assert_called_once_with('restart',{})

    def test_restart_skips_pending_and_missed_but_marks_running_interrupted(self):
        rule=self.create()
        self.now+=3600
        self.ops.tick()
        restarted=Operations(self.manager)
        self.assertEqual(restarted.view()['maintenance']['state'],'skipped')
        restarted.tick();restarted.run_pending();self.manager.execute.assert_not_called()
        self.now+=86400
        missed=Operations(self.manager)
        self.assertGreater(missed.view()['routines'][0]['next_at'],self.now)
        self.assertEqual(missed.view()['history'][0]['reason'],'missed')
        missed.data['maintenance']={'routine_id':rule['id'],'operation':'restart','at':self.now,'deadline':self.now+120,'wait_empty':True,'state':'running'}
        missed.save()
        interrupted=Operations(self.manager)
        self.assertEqual(interrupted.view()['maintenance']['state'],'interrupted')
        self.assertEqual(interrupted.view()['history'][0]['state'],'interrupted')

    def test_pause_and_delete_cancel_pending_without_replaying_on_resume(self):
        rule=self.create()
        self.now+=3600;self.ops.tick()
        self.ops.routine_command({'command':'routine_toggle','id':rule['id'],'enabled':False})
        self.assertEqual(self.ops.view()['maintenance']['state'],'cancelled')
        self.assertFalse(self.ops.view()['upcoming'])
        self.ops.routine_command({'command':'routine_toggle','id':rule['id'],'enabled':True})
        self.assertGreater(self.ops.view()['routines'][0]['next_at'],self.now)
        self.ops.routine_command({'command':'routine_remove','id':rule['id']})
        self.assertFalse(self.ops.view()['routines'])

    def test_one_shot_remains_independent_and_overlap_skips_at_deadline(self):
        self.ops.schedule({'operation':'stop','at':self.now+20*86400,'wait_empty':True})
        self.create(max_wait_minutes=2)
        self.now+=3600;self.ops.tick()
        self.assertNotIn('routine_id',self.ops.view()['maintenance'])
        self.assertEqual(len(self.ops.data['recurring_queue']),1)
        self.now+=121;self.ops.tick()
        self.assertEqual(self.ops.view()['history'][0]['reason'],'deadline')
        self.manager.execute.assert_not_called()

    def test_deadline_before_disruption_is_skipped_and_guard_always_resets(self):
        self.create(operation='install',max_wait_minutes=2)
        self.now+=3600;self.ops.tick()
        self.manager.execute.side_effect=ValueError(DEADLINE_ERROR)
        with self.assertRaises(ValueError):self.ops.run_pending()
        self.assertEqual(self.ops.view()['maintenance']['state'],'skipped')
        self.assertFalse(self.manager.maintenance_wait_empty)
        self.assertIsNone(self.manager.maintenance_deadline)

    def test_failed_occurrence_publish_does_not_advance_schedule_or_execute(self):
        self.create()
        self.now+=3600
        before=copy.deepcopy(self.ops.data)
        with patch.object(self.ops,'save',side_effect=OSError('full')):
            with self.assertRaises(OSError):self.ops.tick()
        self.assertEqual(self.ops.data,before)
        self.manager.submit.assert_not_called()

    def test_moderation_notifications_are_opt_in_and_cannot_ping(self):
        with patch('operations.request') as send:
            self.ops.configure_discord({'url':'https://discord.com/api/webhooks/123/'+'a'*40,'events':['moderation']})
            self.ops.notify('moderation','@everyone account banned')
            self.ops.messages.join()
            self.assertEqual(send.call_args.args[1]['allowed_mentions'],{'parse':[]})

if __name__=='__main__':unittest.main()
