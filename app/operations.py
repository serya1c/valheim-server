"""Maintenance queue, release discovery and opt-in Discord notifications."""
import copy
import json
import math
from pathlib import Path
import queue
import re
import threading
import time
import urllib.request
from configuration import atomic_text

REPO = 'https://github.com/serya1c/valheim-server'
EVENTS = {'server', 'update', 'backup', 'maintenance', 'error'}
ACTIONS = {'restart', 'stop', 'backup', 'install'}
LABELS = {'restart':'Перезапуск', 'stop':'Остановка', 'backup':'Резервная копия', 'install':'Обновление игры и мода'}

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
        task = self.data.get('maintenance')
        if task and task['state'] == 'running':
            task['state'] = 'interrupted'
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
            return {'maintenance':copy.deepcopy(self.data['maintenance']), 'discord':{'configured':bool(self.data['discord']['url']), 'events':list(self.data['discord']['events']), 'delivery':self.delivery}, 'release':dict(self.release)}

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
                task['state']='cancelled'
                try:self.save()
                except Exception:
                    task['state']='pending'
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
            task=self.data['maintenance']
            if task and task['state']=='pending' and self.eligible(task) and not self.manager.busy:
                try:self.manager.submit('maintenance')
                except ValueError:pass

    def run_pending(self):
        with self.lock:
            task=self.data['maintenance']
            if not task or task['state']!='pending' or not self.eligible(task):return
            task['state']='running'
            try:self.save()
            except Exception:
                task['state']='pending'
                raise
        self.notify('maintenance','Началось обслуживание: '+LABELS[task['operation']]+'.')
        try:
            self.manager.maintenance_wait_empty=task['wait_empty']
            self.manager.guard_maintenance()
            self.manager.execute(task['operation'],{})
        except Exception:
            with self.lock:task['state']='error';self.save()
            raise
        else:
            with self.lock:task['state']='done';self.save()
            self.notify('maintenance','Обслуживание завершено: '+LABELS[task['operation']]+'.')
        finally:
            self.manager.maintenance_wait_empty=False
