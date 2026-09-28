'use strict';
let csrf = '', polling = false, pendingApproval = null;
const $ = id => document.getElementById(id);
const fmtTime = ts => ts ? new Date(ts * 1000).toLocaleString('ru-RU') : '—';
const bytes = n => n >= 1073741824 ? (n / 1073741824).toFixed(1) + ' ГБ' : (n / 1048576).toFixed(1) + ' МБ';
const duration = n => Math.floor(n / 3600) + ' ч ' + Math.floor(n % 3600 / 60) + ' мин';
async function api(url, data) {
  const options = data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Hearth':'1','X-CSRF-Token':csrf},body:JSON.stringify(data)};
  const response = await fetch(url, options);
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) showLogin();
    throw new Error(result.error || 'Ошибка запроса');
  }
  return result;
}
function showLogin() { $('dashboard').hidden = true; $('login').hidden = false; csrf = ''; window.dispatchEvent(new Event('hearth-logout')); }
function showDashboard() { $('login').hidden = true; $('dashboard').hidden = false; window.dispatchEvent(new Event('hearth-login')); }
function cell(row, text) { const td = document.createElement('td'); td.textContent = text; row.append(td); }
function table(id, rows, render, cols) {
  const fragment = document.createDocumentFragment();
  if (!rows.length) { const tr = document.createElement('tr'); const td = document.createElement('td'); td.colSpan = cols; td.className = 'empty'; td.textContent = 'Пока нет данных'; tr.append(td); fragment.append(tr); }
  rows.forEach(row => { const tr = document.createElement('tr'); render(tr, row); fragment.append(tr); });
  $(id).replaceChildren(fragment);
}
function confirmAction(message) {
  return new Promise(resolve => {
    $('confirm-text').textContent = message;
    const dlg = $('confirm'); dlg.returnValue = 'cancel';
    dlg.addEventListener('close', () => resolve(dlg.returnValue === 'ok'), {once:true}); dlg.showModal();
  });
}
async function action(name, data = {}) {
  const prompts = {stop:'Остановить сервер? Игроки будут отключены. Мир сохранится перед выходом.',restart:'Перезапустить сервер? Текущие подключения будут закрыты.',backup:'Сервер остановится для согласованной копии мира, затем запустится снова, если работал.',install:'Установить последнюю версию в режиме, выбранном в настройках сервера, и проверить запуск? После проверки сервер остановится для резервной копии и переключения.',restore:'Заменить текущий мир выбранной копией? Более поздний прогресс будет потерян. Текущий мир предварительно сохранится отдельно.',rollback:'Вернуть предыдущий сервер, мод, конфигурацию и мир до обновления? Прогресс после обновления останется только в отдельной резервной копии.'};
  if (data.approval_token) prompts.install = `Одобрить Valheim ${pendingApproval?.actual} + V+ ${pendingApproval?.mod}? Автор мода указал Valheim ${pendingApproval?.declared}. Сервер повторит проверку, сохранит мир и настройки и попробует обновиться. При неудачном запуске будет предпринят автоматический откат.`;
  if (prompts[name] && !await confirmAction(prompts[name])) return;
  try { await api('/api/action', {action:name,...data}); await refresh(); }
  catch(e) { $('job').textContent = e.message; $('job').className = 'notice error'; }
}
async function refresh() {
  if (!csrf || polling) return;
  polling = true;
  try {
    const s = await api('/api/status');
    window.dispatchEvent(new CustomEvent('hearth-status',{detail:s}));
    $('connection').textContent = '● Панель на связи';
    $('world-name').textContent = s.world;
    $('project-link').href=s.site_url;
    $('update-mode').textContent='Следующая установка: '+(s.target_mode==='vanilla'?'ванильный Valheim, без BepInEx и V+.':'Valheim Plus от Grantapher.')+(s.versions && (s.versions.mode||'plus')!==s.target_mode?' Сейчас установлен другой режим. Обновление переключит его с резервной копией мира.':'');
    $('version-label').textContent = s.versions ? `Valheim ${s.versions.game} · ${s.versions.mode==='vanilla'?'Без модов':'Valheim Plus '+s.versions.mod+' / Grantapher'}` : 'Ожидает установки · смотрите журнал';
    $('server-state').textContent = s.running ? (s.online ? 'В сети' : 'Нет ответа A2S') : 'Остановлен';
    $('uptime').textContent = s.running ? 'Процесс работает: ' + duration(s.uptime) : 'Процесс не запущен';
    $('online').textContent = s.online ? s.online.count : '—';
    $('world-size').textContent = bytes(s.files.reduce((a,f) => a+f.bytes,0));
    $('world-time').textContent = s.files.length ? 'Изменено: '+fmtTime(Math.max(...s.files.map(f=>f.modified))) : 'Мир ещё не создан';
    $('disk').textContent = bytes(s.free_bytes);
    $('job').textContent = (s.busy ? '◌ ' : '') + s.job.message;
    $('job').className = 'notice' + (s.job.state === 'error' ? ' error' : '');
    document.querySelectorAll('[data-action], #update-form button').forEach(b => b.disabled = s.busy);
    $('rollback').disabled = s.busy || !s.rollback;
    pendingApproval = s.compatibility;
    $('compatibility-approval').hidden = !pendingApproval;
    $('approve-update').disabled = s.busy || !pendingApproval;
    if (pendingApproval) $('compatibility-details').textContent = `Steam: Valheim ${pendingApproval.actual}. Мод: V+ ${pendingApproval.mod}. Заявлено автором: Valheim ${pendingApproval.declared}. Одобрение доступно до ${fmtTime(pendingApproval.expires)}; после перезапуска панели проверку нужно повторить.`;
    table('players-body', s.players, (tr,p) => { cell(tr, (s.online?.names.includes(p.name)?'● ':'') + p.name); cell(tr,p.joins); cell(tr,duration(p.seconds)); cell(tr,fmtTime(p.last_seen)); },4);
    const kinds = {system:'Система',connection:'Подключение',action:'Действие',update:'Обновление',error:'Ошибка',backup:'Копия',restore:'Восстановление',config:'Настройки',export:'Экспорт',import:'Импорт'};
    table('events-body', s.events, (tr,e) => { cell(tr,fmtTime(e.ts)); cell(tr,kinds[e.kind] || e.kind); cell(tr,e.message); },3);
    $('world-files').replaceChildren();
    s.files.sort((a,b)=>b.modified-a.modified).slice(0,30).forEach(f=>{
      const row=document.createElement('div');row.className='file-row';const title=document.createElement('strong');title.textContent=f.path;row.append(title,document.createTextNode(bytes(f.bytes)+' · '+fmtTime(f.modified)));$('world-files').append(row);
    });
    if (!s.files.length) $('world-files').textContent='Сохранений пока нет';
    $('backups').replaceChildren();
    s.backups.forEach(b=>{
      const row=document.createElement('div');row.className='file-row';const title=document.createElement('strong');title.textContent=b.name;
      const link=document.createElement('a');link.textContent='Скачать · '+bytes(b.bytes);link.href='/api/backup/'+encodeURIComponent(b.name);
      const btn=document.createElement('button');btn.textContent='Восстановить';btn.disabled=s.busy;btn.onclick=()=>action('restore',{name:b.name});row.append(title,link,btn);$('backups').append(row);
    });
    if (!s.backups.length) $('backups').textContent='Резервных копий пока нет';
    $('logs').textContent=s.logs.join('\n');
  } catch(e) { $('connection').textContent='Нет связи с панелью'; }
  finally { polling=false; }
}
$('login-form').addEventListener('submit', async e=>{e.preventDefault();try { const s=await api('/api/login',{password:$('password').value});csrf=s.csrf;$('password').value='';$('login-error').textContent='';showDashboard();await refresh(); }catch(err){$('login-error').textContent=err.message;}});
$('logout').onclick=async()=>{try{await api('/api/logout',{});}finally{showLogin();}};
document.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>action(b.dataset.action));
$('approve-update').onclick=()=>{if(pendingApproval) action('install',{approval_token:pendingApproval.token});};
$('update-form').onsubmit=e=>{e.preventDefault();action('install');};
(async()=>{try{const s=await api('/api/session');csrf=s.csrf;showDashboard();await refresh();}catch{}setInterval(refresh,5000);})();
