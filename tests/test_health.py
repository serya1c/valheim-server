import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from health import HealthMonitor, container_memory, process_sample, selected_world


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        (self.base / 'backups').mkdir()
        (self.base / 'saves/worlds_local').mkdir(parents=True)
        self.proc = self.base / 'proc'
        (self.proc / 'self').mkdir(parents=True)
        self.manager = SimpleNamespace(base=self.base, config=MagicMock(), online=None,
                                       started=time.time() - 1000, proc=SimpleNamespace(pid=123))
        self.running = True
        self.manager.running = lambda: self.running
        self.manager.config.load.return_value = {'world_name': 'Loki'}
        self.monitor = HealthMonitor(self.manager, proc_root=self.proc, container=False)

    def tearDown(self):
        if self.monitor.worker:
            self.monitor.worker.join(timeout=2)
        self.temporary.cleanup()

    def write_process(self, ticks=300, started=50, rss=2048):
        path = self.proc / '123'
        path.mkdir(exist_ok=True)
        # After the comm field: state=field3, utime=field14, stime=field15.
        fields = ['S'] + ['0'] * 21
        fields[11], fields[12], fields[19] = str(ticks - 50), '50', str(started)
        (path / 'stat').write_text('123 (game (name) with spaces) ' + ' '.join(fields))
        (path / 'status').write_text(f'Name:\tgame\nVmRSS:\t{rss} kB\n')

    def test_cpu_uses_process_ticks_one_core_scale_and_resets_on_pid_reuse(self):
        self.write_process()
        self.assertEqual(process_sample(self.proc, 123), ((123, 50), 300, 2048 * 1024))
        with patch('health.os.sysconf', return_value=100, create=True), patch('health.time.monotonic', return_value=10):
            self.monitor.sample()
        self.assertIsNone(self.monitor.view()['process']['cpu_percent'])
        self.write_process(ticks=500)
        with patch('health.os.sysconf', return_value=100, create=True), patch('health.time.monotonic', return_value=11):
            self.monitor.sample()
        self.assertEqual(self.monitor.view()['process']['cpu_percent'], 200)
        self.assertEqual(self.monitor.view()['process']['rss_bytes'], 2048 * 1024)
        self.write_process(ticks=700, started=51)
        with patch('health.os.sysconf', return_value=100, create=True), patch('health.time.monotonic', return_value=12):
            self.monitor.sample()
        self.assertIsNone(self.monitor.view()['process']['cpu_percent'])

    def test_missing_proc_is_unavailable_and_disk_is_data_filesystem(self):
        with patch('health.shutil.disk_usage', return_value=SimpleNamespace(free=10000, total=20000)) as disk:
            self.monitor.sample()
        disk.assert_called_once_with(self.base)
        result = self.monitor.view()
        self.assertIsNone(result['process']['cpu_percent'])
        self.assertIsNone(result['process']['rss_bytes'])
        self.assertIsNone(result['container']['memory_bytes'])
        self.assertEqual(result['disk'], {'free_bytes': 10000, 'total_bytes': 20000})

    def cgroup(self, kind, membership, mount_root='/'):
        mount = self.base / 'cgroup'
        mount.mkdir(exist_ok=True)
        relative = Path(membership).relative_to(mount_root) if membership != '/' else Path('.')
        directory = mount / relative
        directory.mkdir(parents=True, exist_ok=True)
        controllers = '' if kind == 'cgroup2' else 'memory'
        (self.proc / 'self/cgroup').write_text(f'0:{controllers}:{membership}\n')
        (self.proc / 'self/mountinfo').write_text(f'1 0 0:1 {mount_root} {mount.as_posix()} rw - {kind} cgroup rw,memory\n')
        return directory

    def test_cgroup_v2_reads_current_membership_not_mount_root_usage(self):
        path = self.cgroup('cgroup2', '/docker/loki')
        (path / 'memory.current').write_text('900')
        (path / 'memory.max').write_text('1000')
        (self.base / 'cgroup/memory.current').write_text('999999')
        (self.base / 'cgroup/memory.max').write_text('max')
        self.assertEqual(container_memory(self.proc), {'memory_bytes': 900, 'memory_limit_bytes': 1000})
        (path / 'memory.max').write_text('max')
        self.assertIsNone(container_memory(self.proc)['memory_limit_bytes'])

    def test_cgroup_v1_and_namespaced_mount_root_unlimited_sentinel(self):
        path = self.cgroup('cgroup', '/', mount_root='/docker/loki')
        (path / 'memory.usage_in_bytes').write_text('4096')
        (path / 'memory.limit_in_bytes').write_text(str(9223372036854771712))
        self.assertEqual(container_memory(self.proc), {'memory_bytes': 4096, 'memory_limit_bytes': None})
        (path / 'memory.limit_in_bytes').write_text('8192')
        self.assertEqual(container_memory(self.proc)['memory_limit_bytes'], 8192)

    def test_only_selected_classic_world_pair_counts_other_backups_are_ignored(self):
        folder = self.base / 'saves/worlds_local'
        for name, at in [('Loki.db', 100), ('Loki.fwl', 200), ('Other.db', 900), ('Loki_backup_auto.db', 1000)]:
            path = folder / name
            path.write_bytes(b'world')
            os.utime(path, (at, at))
        result = selected_world(self.base, 'Loki')
        self.assertEqual(result['last_save_at'], 200)
        self.assertEqual(result['format'], 'classic')
        (folder / 'Loki.fwl').unlink()
        self.assertIsNone(selected_world(self.base, 'Loki')['last_save_at'])
        self.assertTrue(selected_world(self.base, 'Loki')['error'])

    def test_chunked_world_complete_generation_and_partial_or_foreign_file_rejected(self):
        folder = self.base / 'saves/worlds_local/Loki'
        folder.mkdir()
        for suffix, at in [('db2', 100), ('fwl2', 200), ('chunks', 250), ('ok', 300)]:
            path = folder / ('_main.6.' + suffix)
            path.write_bytes(b'world')
            os.utime(path, (at, at))
        chunk = folder / '1e_20__1_1.chunk'
        chunk.write_bytes(b'chunk')
        os.utime(chunk, (150, 150))
        self.assertEqual(selected_world(self.base, 'Loki')['last_save_at'], 300)
        self.assertEqual(selected_world(self.base, 'Loki')['format'], 'directory')
        (folder / '_main.6.ok').unlink()
        self.assertTrue(selected_world(self.base, 'Loki')['error'])
        self.assertIsNone(selected_world(self.base, 'Loki')['last_save_at'])

    def test_backup_only_counts_recorded_final_archive_persists_and_detects_change(self):
        name = '20261004-123000-a1b2c3-manual.tar.gz'
        path = self.base / 'backups' / name
        path.write_bytes(b'complete archive fixture')
        (self.base / 'backups' / (name + '.tmp')).write_bytes(b'incomplete')
        self.monitor.sample()
        self.assertIsNone(self.monitor.view()['backup']['last_success_at'])
        self.assertFalse(self.monitor.record_backup(name + '.tmp'))
        self.assertTrue(self.monitor.record_backup(name, 1234))
        resumed = HealthMonitor(self.manager, proc_root=self.proc, container=False)
        resumed.sample()
        self.assertEqual(resumed.view()['backup']['last_success_at'], 1234)
        path.write_bytes(b'externally modified')
        resumed.last_backup_check = None
        resumed.sample()
        self.assertIsNone(resumed.view()['backup']['last_success_at'])

    def test_legacy_backup_requires_success_event_and_existing_final_file(self):
        name = '20261004-123000-a1b2c3-scheduled.tar.gz'
        path = self.base / 'backups' / name
        path.write_bytes(b'completed old-version archive fixture')
        with sqlite3.connect(self.base / 'panel.sqlite') as db:
            db.execute('CREATE TABLE events(ts REAL,kind TEXT,message TEXT)')
            db.executemany('INSERT INTO events VALUES(?,?,?)', [(100, 'backup', name), (300, 'backup', name + '.tmp'), (500, 'backup', '20261004-123000-deadbe-missing.tar.gz')])
        db.close()
        self.monitor.sample()
        self.assertEqual(self.monitor.view()['backup']['last_success_at'], 100)
        path.unlink()
        self.monitor.last_backup_check = None
        self.monitor.sample()
        self.assertIsNone(self.monitor.view()['backup']['last_success_at'])

    def test_running_is_separate_from_a2s_age_and_restart_invalidates_old_response(self):
        now = time.time()
        self.manager.online = {'at': now - 10}
        view = self.monitor.view()
        self.assertTrue(view['process']['running'])
        self.assertTrue(view['a2s']['fresh'])
        self.assertGreaterEqual(view['a2s']['age_seconds'], 10)
        self.manager.online = None
        with patch('health.time.time', return_value=now + 40):
            view = self.monitor.view()
        self.assertFalse(view['a2s']['fresh'])
        self.assertIn('a2s_timeout', [d['code'] for d in view['diagnostics']])
        self.manager.started = now + 1
        self.manager.online = {'at': now - 10}
        with patch('health.time.time', return_value=now + 2):
            view = self.monitor.view()
        self.assertIsNone(view['a2s']['last_response_at'])
        self.assertIn('startup', [d['code'] for d in view['diagnostics']])
        self.running = False
        self.assertFalse(self.monitor.view()['a2s']['fresh'])
        self.assertIn('stopped', [d['code'] for d in self.monitor.view()['diagnostics']])

    def test_view_does_not_scan_and_warnings_use_container_and_data_volume(self):
        self.monitor.data['disk'] = {'free_bytes': 100, 'total_bytes': 10000}
        self.monitor.data['container'] = {'memory_bytes': 950, 'memory_limit_bytes': 1000}
        with patch('health.shutil.disk_usage', side_effect=AssertionError('status must not scan')), patch('health.selected_world', side_effect=AssertionError('status must not scan')):
            result = self.monitor.view()
        self.assertIn('disk_low', [d['code'] for d in result['diagnostics']])
        self.assertIn('memory_limit', [d['code'] for d in result['diagnostics']])
        result['disk']['free_bytes'] = 0
        self.assertEqual(self.monitor.data['disk']['free_bytes'], 100)

    def test_tick_does_not_wait_for_sampler_or_start_overlapping_workers(self):
        gate = threading.Event()
        with patch.object(self.monitor, 'sample', side_effect=lambda: gate.wait(2)) as sampler:
            self.monitor.tick()
            first = self.monitor.worker
            self.monitor.last_scheduled = None
            self.monitor.tick()
            self.assertIs(first, self.monitor.worker)
            self.assertEqual(sampler.call_count, 1)
            gate.set()
            first.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
