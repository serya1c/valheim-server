"""Maintenance queue, release discovery and opt-in Discord notifications."""
import copy
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import queue
import re
import threading
import time
import urllib.request
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from configuration import atomic_text

REPO = 'https://github.com/serya1c/valheim-server'
EVENTS = {'server', 'update', 'backup', 'maintenance', 'error', 'moderation'}
ACTIONS = {'restart', 'stop', 'backup', 'install'}
LABELS = {'restart':'Перезапуск', 'stop':'Остановка', 'backup':'Резервная копия', 'install':'Обновление игры и мода'}
ROUTINE_ERROR = 'Проверьте действие, повторение, дни недели, время, часовой пояс и окно ожидания (2–1440 минут)'
DEADLINE_ERROR = 'Окно обслуживания истекло: задача пропущена без отключения игроков'

def next_occurrence(routine, after):
    """First valid wall-clock occurrence strictly after a UTC timestamp.

    Missing DST times are skipped. Ambiguous times use the first occurrence
    only, so a daily task cannot run twice when clocks move backwards.
    """
    zone = ZoneInfo(routine['timezone'])
    hour, minute = map(int, routine['time'].split(':'))
    day = datetime.fromtimestamp(after, zone).date()
    for offset in range(15):
        candidate_day = day + timedelta(days=offset)
        if routine['frequency'] == 'weekly' and candidate_day.weekday() not in routine['weekdays']:
            continue
        candidate = datetime.combine(candidate_day, datetime.min.time()).replace(hour=hour, minute=minute, tzinfo=zone, fold=0)
        stamp = candidate.timestamp()
        round_trip = datetime.fromtimestamp(stamp, zone)
        if (round_trip.hour, round_trip.minute, round_trip.date()) != (hour, minute, candidate_day):
            continue
        if stamp > after:
            return stamp
    raise ValueError(ROUTINE_ERROR)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def request(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={'User-Agent':'Hearth-Valheim', 'Content-Type':'application/json', 'Accept':'application/json'})
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=8) as response:
        return response.read(1024 * 1024)

class Operations:
    def __init__(self, manager):
        self.manager = manager
        self.path = manager.base/'operations.json'
        self.lock = threading.RLock()
        self.data = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'discord':{'url':'','events':[]}, 'maintenance':None}
        self.data.setdefault('routines', [])
        self.data.setdefault('recurring_queue', [])
        self.data.setdefault('history', [])
        task = self.data.get('maintenance')
        recovered = False
        if task and task['state'] == 'running':
            task['state'] = 'interrupted'
            if task.get('routine_id'):
                self._remember(task, 'interrupted', 'panel_restart')
            recovered = True
        elif task and task['state'] == 'pending' and task.get('routine_id'):
            task['state'] = 'skipped'
            self._remember(task, 'skipped', 'panel_restart')
            recovered = True
        for pending in self.data['recurring_queue']:
            self._remember(pending, 'skipped', 'panel_restart')
            recovered = True
        self.data['recurring_queue'] = []
        now = time.time()
        for routine in self.data['routines']:
            if routine['enabled'] and routine.get('next_at') is not None and routine['next_at'] <= now:
                self._remember({'routine_id':routine['id'], 'operation':routine['operation'], 'at':routine['next_at']}, 'skipped', 'missed')
                routine['next_at'] = next_occurrence(routine, now)
                recovered = True
        if recovered:
            self.save()
        self.empty_since = None
        self.release = {'current':(Path(__file__).parent/'PANEL_VERSION').read_text(encoding='utf-8').strip(), 'latest':None, 'checked':None}
        self.messages = queue.Queue(maxsize=20)
        self.worker = None
        self.sent = {}
        self.delivery = None
        self.ready = False

    def save(self):
        atomic_text(self.path, json.dumps(self.data, ensure_ascii=False))
        self.path.chmod(0o600)

    def view(self):
        with self.lock:
            return {'maintenance':copy.deepcopy(self.data['maintenance']), 'discord':{'configured':bool(self.data['discord']['url']), 'events':list(self.data['discord']['events']), 'delivery':self.delivery}, 'release':dict(self.release),
                    'routines':copy.deepcopy(self.data['routines']), 'upcoming':self._upcoming(), 'history':copy.deepcopy(self.data['history'])}

    def _remember(self, task, state, reason=None):
        item = {'routine_id':task['routine_id'], 'operation':task['operation'], 'at':task['at'], 'state':state, 'finished_at':time.time(), 'reason':reason}
        self.data['history'] = [item, *self.data['history']][:50]
        for routine in self.data['routines']:
            if routine['id'] == task['routine_id']:
                routine['last'] = copy.deepcopy(item)

    def _upcoming(self):
        now = time.time()
        result = []
        active = self.data['maintenance']
        for task in [*self.data['recurring_queue'], *([active] if active and active.get('routine_id') and active['state'] in ('pending','running') else [])]:
            result.append({**copy.deepcopy(task), 'timezone':next((r['timezone'] for r in self.data['routines'] if r['id']==task['routine_id']), 'UTC')})
        for routine in self.data['routines']:
            if not routine['enabled']:
                continue
            stamp = routine['next_at']
            while stamp is not None and stamp <= now + 7*86400:
                result.append({'routine_id':routine['id'], 'operation':routine['operation'], 'at':stamp, 'deadline':stamp+routine['max_wait_minutes']*60, 'timezone':routine['timezone'], 'state':'scheduled'})
                stamp = next_occurrence(routine, stamp)
        return sorted(result, key=lambda t:(t['at'],t['routine_id']))[:100]

    def save_routine(self, values):
        action, frequency = values.get('operation'), values.get('frequency')
        weekdays, wall_time, zone = values.get('weekdays', []), values.get('time'), values.get('timezone')
        enabled, minutes = values.get('enabled'), values.get('max_wait_minutes')
        if action not in ACTIONS or frequency not in ('daily','weekly') or type(enabled) is not bool or type(minutes) is not int or not 2 <= minutes <= 1440:
            raise ValueError(ROUTINE_ERROR)
        if not isinstance(weekdays,list) or any(type(d) is not int or not 0<=d<=6 for d in weekdays) or frequency=='weekly' and not weekdays:
            raise ValueError(ROUTINE_ERROR)
        if not isinstance(wall_time,str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',wall_time) or not isinstance(zone,str) or len(zone)>100:
            raise ValueError(ROUTINE_ERROR)
        try:ZoneInfo(zone)
        except (ValueError, ZoneInfoNotFoundError):raise ValueError(ROUTINE_ERROR) from None
        rid = values.get('id')
        if rid is not None and (not isinstance(rid,str) or not re.fullmatch(r'[a-f0-9]{12}',rid)):
            raise ValueError('Расписание не найдено')
        with self.lock:
            existing = next((r for r in self.data['routines'] if r['id']==rid),None)
            if rid and not existing:raise ValueError('Расписание не найдено')
            if not existing and len(self.data['routines'])>=20:raise ValueError('Можно создать не более 20 расписаний')
            routine = {'id':rid or uuid.uuid4().hex[:12], 'operation':action, 'frequency':frequency, 'weekdays':sorted(set(weekdays)) if frequency=='weekly' else [],
                       'time':wall_time, 'timezone':zone, 'enabled':enabled, 'wait_empty':True, 'max_wait_minutes':minutes, 'last':existing.get('last') if existing else None}
            routine['next_at'] = next_occurrence(routine, time.time()) if enabled else None
            before = copy.deepcopy(self.data)
            if existing:
                self._cancel_routine_pending(rid)
                self.data['routines'][self.data['routines'].index(existing)] = routine
            else:self.data['routines'].append(routine)
            try:self.save()
            except Exception:self.data=before;raise

    def _cancel_routine_pending(self, rid):
        tasks = [t for t in self.data['recurring_queue'] if t['routine_id']==rid]
        self.data['recurring_queue'] = [t for t in self.data['recurring_queue'] if t['routine_id']!=rid]
        current = self.data['maintenance']
        if current and current.get('routine_id')==rid and current['state']=='pending':
            current['state']='cancelled'
            tasks.append(current)
            self.empty_since=None
        for task in tasks:self._remember(task,'cancelled','changed')

    def routine_command(self, values):
        rid, command = values.get('id'), values.get('command')
        with self.lock:
            routine = next((r for r in self.data['routines'] if r['id']==rid),None)
            if not routine:raise ValueError('Расписание не найдено')
            if command not in ('routine_toggle','routine_remove') or command=='routine_toggle' and type(values.get('enabled')) is not bool:
                raise ValueError('Неизвестное действие с расписанием')
            before=copy.deepcopy(self.data)
            self._cancel_routine_pending(rid)
            if command=='routine_remove':self.data['routines'].remove(routine)
            else:
                routine['enabled']=values['enabled']
                routine['next_at']=next_occurrence(routine,time.time()) if routine['enabled'] else None
            try:self.save()
            except Exception:self.data=before;raise

    def configure_discord(self, values):
        events = values.get('events')
        url = values.get('url', '')
        if not isinstance(events,list) or any(e not in EVENTS for e in events) or not isinstance(url,str):
            raise ValueError('Неверные настройки уведомлений')
        if url and not re.fullmatch(r'https://discord\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]{20,200}',url):
            raise ValueError('Укажите HTTPS webhook discord.com без дополнительных параметров')
        with self.lock:
            old = self.data['discord']
            self.data['discord'] = {'url':'' if values.get('remove') is True else url or old['url'], 'events':sorted(set(events))}
            try:self.save()
            except Exception:
                self.data['discord']=old
                raise
            self.sent.clear()
            self.delivery=None

    def notify(self, event, text, test=False):
        with self.lock:
            settings = self.data['discord']
            if not settings['url'] or (not test and event not in settings['events']):return
            now=time.time()
            key=(event,text)
            if now-self.sent.get(key,0)<60:return
            self.sent[key]=now
            self.sent={k:v for k,v in self.sent.items() if now-v<60}
            try:title=self.manager.config.load()['server']['name']
            except Exception:title='Hearth'
            content=(title+'\n'+text)[:1900]
            try:self.messages.put_nowait((settings['url'],content))
            except queue.Full:
                self.delivery='Очередь уведомлений заполнена'
                return
            self.delivery='Уведомление в очереди'
            if not self.worker or not self.worker.is_alive():
                self.worker=threading.Thread(target=self.deliver,daemon=True);self.worker.start()

    def deliver(self):
        while True:
            try:url,content=self.messages.get(timeout=1)
            except queue.Empty:
                with self.lock:
                    if self.messages.empty():self.worker=None;return
                continue
            try:
                with self.lock:
                    if url!=self.data['discord']['url']:continue
                request(url+'?wait=true',{'content':content,'allowed_mentions':{'parse':[]}})
                self.delivery='Уведомление доставлено'
            except Exception:
                self.delivery='Discord недоступен или отклонил уведомление. Проверьте webhook.'
            finally:self.messages.task_done()

    def check_release(self):
        with self.lock:
            if self.release['checked'] and time.time()-self.release['checked']<60:return
            try:
                result=json.loads(request('https://api.github.com/repos/serya1c/valheim-server/releases/latest'))
                tag=result.get('tag_name','')
                if result.get('draft') or result.get('prerelease') or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+',tag):raise ValueError()
                current=tuple(map(int,self.release['current'].split('-')[0].split('.')))
                latest=tuple(map(int,tag[1:].split('.')))
                self.release.update(latest=tag, url=REPO+'/releases/tag/'+tag, available=latest>current or latest==current and '-' in self.release['current'], error=None)
            except Exception:
                self.release['error']='Не удалось проверить релизы GitHub. Повторите позже.'
            self.release['checked']=time.time()

    def schedule(self, values):
        action=values.get('operation');at=values.get('at');wait=values.get('wait_empty')
        if action not in ACTIONS or type(at) not in (int,float) or not math.isfinite(at) or not time.time()-60<=at<=time.time()+30*86400 or type(wait) is not bool:
            raise ValueError('Выберите действие и время в ближайшие 30 дней')
        with self.lock:
            if self.data['maintenance'] and self.data['maintenance']['state'] in ('pending','running'):
                raise ValueError('Сначала отмените текущую задачу обслуживания')
            previous=self.data['maintenance']
            self.data['maintenance']={'operation':action,'at':at,'wait_empty':wait,'state':'pending'}
            try:self.save()
            except Exception:
                self.data['maintenance']=previous
                raise
            self.empty_since=None
        self.notify('maintenance','Запланировано обслуживание: '+LABELS[action]+f'. Не раньше <t:{int(at)}:F>. '+self.manager.config.load()['landing']['site_url'])

    def cancel(self):
        with self.lock:
            task=self.data['maintenance']
            if task and task['state']=='pending':
                previous=copy.deepcopy(self.data)
                task['state']='cancelled'
                if task.get('routine_id'):self._remember(task,'cancelled','manual')
                try:self.save()
                except Exception:
                    self.data=previous
                    raise
                self.empty_since=None
                self.notify('maintenance','Запланированное обслуживание отменено.')

    def eligible(self, task):
        now=time.time()
        if now<task['at']:return False
        if not task['wait_empty'] or not self.manager.running():return True
        online=self.manager.online
        if not online or now-online.get('at',0)>30 or online['count']!=0:
            self.empty_since=None;return False
        if self.empty_since is None:self.empty_since=now
        return now-self.empty_since>=60

    def tick(self):
        ready=bool(self.manager.running() and self.manager.online and time.time()-self.manager.online.get('at',0)<30)
        if ready and not self.ready:self.notify('server','Сервер отвечает на запросы. Можно подключаться.')
        if self.ready and not self.manager.running():self.notify('server','Сервер остановлен.')
        self.ready=ready
        with self.lock:
            self._refresh_recurring()
            task=self.data['maintenance']
            if task and task['state']=='pending' and self.eligible(task) and not self.manager.busy:
                try:self.manager.submit('maintenance')
                except ValueError:pass

    def _refresh_recurring(self):
        now=time.time()
        before=copy.deepcopy(self.data)
        task=self.data['maintenance']
        if task and task.get('routine_id') and task['state']=='pending' and now>=task['deadline']:
            task['state']='skipped'
            self._remember(task,'skipped','deadline')
            self.empty_since=None
        kept=[]
        for waiting in self.data['recurring_queue']:
            if now>=waiting['deadline']:self._remember(waiting,'skipped','deadline')
            else:kept.append(waiting)
        self.data['recurring_queue']=kept
        for routine in self.data['routines']:
            if not routine['enabled'] or routine['next_at'] is None or routine['next_at']>now:
                continue
            occurrence={'routine_id':routine['id'], 'operation':routine['operation'], 'at':routine['next_at'], 'wait_empty':True, 'state':'pending', 'deadline':routine['next_at']+routine['max_wait_minutes']*60}
            routine['next_at']=next_occurrence(routine,now)
            if now>=occurrence['deadline']:
                self._remember(occurrence,'skipped','missed')
            elif any(t['routine_id']==routine['id'] for t in self.data['recurring_queue']) or task and task.get('routine_id')==routine['id'] and task['state'] in ('pending','running'):
                self._remember(occurrence,'skipped','overlap')
            else:self.data['recurring_queue'].append(occurrence)
        if (not task or task['state'] not in ('pending','running')) and self.data['recurring_queue']:
            self.data['recurring_queue'].sort(key=lambda t:(t['at'],t['routine_id']))
            self.data['maintenance']=self.data['recurring_queue'].pop(0)
            self.empty_since=None
        if self.data!=before:
            try:self.save()
            except Exception:self.data=before;raise
            previous_history=before['history']
            for outcome in self.data['history']:
                if outcome not in previous_history and outcome['state']=='skipped':
                    self.notify('maintenance','Запуск по расписанию пропущен: '+LABELS[outcome['operation']]+'. Игроки не отключены.')

    def run_pending(self):
        with self.lock:
            task=self.data['maintenance']
            if task and task.get('routine_id') and task['state']=='pending' and time.time()>=task['deadline']:
                previous=copy.deepcopy(self.data)
                task['state']='skipped'
                self._remember(task,'skipped','deadline')
                try:self.save()
                except Exception:self.data=previous;raise
                return
            if not task or task['state']!='pending' or not self.eligible(task):return
            task['state']='running'
            try:self.save()
            except Exception:
                task['state']='pending'
                raise
        self.notify('maintenance','Началось обслуживание: '+LABELS[task['operation']]+'.')
        try:
            self.manager.maintenance_wait_empty=task['wait_empty']
            self.manager.maintenance_deadline=task.get('deadline')
            self.manager.guard_maintenance()
            self.manager.execute('scheduled' if task.get('routine_id') and task['operation']=='backup' else task['operation'],{})
        except Exception as error:
            with self.lock:
                task['state']='skipped' if task.get('routine_id') and str(error)==DEADLINE_ERROR else 'error'
                if task.get('routine_id'):self._remember(task,task['state'],'deadline' if task['state']=='skipped' else 'operation')
                self.save()
            raise
        else:
            with self.lock:
                task['state']='done'
                if task.get('routine_id'):self._remember(task,'done')
                self.save()
            self.notify('maintenance','Обслуживание завершено: '+LABELS[task['operation']]+'.')
        finally:
            self.manager.maintenance_wait_empty=False
            self.manager.maintenance_deadline=None
