'use strict';
const el=id=>document.getElementById(id);
let connectAddress='',pending=false,lastPublic=null;
function renderDescription(){if(!lastPublic)return;document.title=lastPublic.title+' — '+(I18n.language==='en'?'Valheim server':'сервер Valheim')+' · '+(lastPublic.mode==='vanilla'?I18n.t('Без модов'):lastPublic.mode==='modded'?'BepInEx':'Valheim Plus');const text=I18n.language==='en'?(lastPublic.description_en||lastPublic.description):lastPublic.description;setText('server-description',text);document.querySelector('meta[property="og:title"]').content=document.title;document.querySelector('meta[name=description]').content=text;document.querySelector('meta[property="og:description"]').content=text;}
function renderMaintenance(){
 if(!lastPublic)return;
 const data=lastPublic;
 setText('status-note',data.players!==null?'Состояние обновляется каждые 30 секунд.':data.running?'Процесс сервера запущен. Число игроков пока неизвестно: сервер не отвечает на запрос статистики.':'Сервер сейчас остановлен. Инструкция и адрес остаются доступными.');
 if(data.maintenance&&['pending','running'].includes(data.maintenance.state))setText('status-note',I18n.t(data.maintenance.state==='running'?'Сервер на обслуживании':'Запланировано обслуживание')+' · '+new Date(data.maintenance.at*1000).toLocaleString(I18n.locale)+(data.maintenance.wait_empty?' · '+I18n.t('Дождаться пустого сервера'):''));
}
function renderClientMods(){if(!lastPublic)return;const data=lastPublic;const bundle=data.client_mods;const bundleLink=el('client-mods-download');bundleLink.hidden=!bundle;bundleLink.href=bundle?bundle.url:'#';const note=el('client-mods-note');note.hidden=!bundle;note.dataset.i18nSkip='';note.textContent=bundle?I18n.t('Клиентский набор: ')+(bundle.packages.length?bundle.packages.map(p=>p.name+' '+p.version).join(', '):'BepInEx'):'';}
window.addEventListener('hearth-language',()=>{renderDescription();renderMaintenance();renderClientMods();});
function setText(id,value){el(id).textContent=value;}
async function refreshPublic(){
 if(pending)return;pending=true;
 try{
  const response=await fetch('/api/public',{cache:'no-store'});
  if(!response.ok)throw new Error('Unavailable');
  const data=await response.json();lastPublic=data;
  document.querySelectorAll('[data-server-name]').forEach(node=>{
   // Preserve the small navigation subtitle without using HTML from settings.
   if(node.querySelector('small')){node.firstChild.textContent=data.title;}else node.textContent=data.title;
  });
  const plus=data.mode==='plus', modded=data.mode==='modded', hasMods=data.mode!=='vanilla';
  document.querySelectorAll('[data-listing]').forEach(n=>n.hidden=!data.public_listing);
  document.querySelectorAll('[data-site-url]').forEach(n=>n.textContent=data.site_url);
  document.querySelectorAll('[data-site-link]').forEach(n=>n.href=data.site_url);
  document.querySelectorAll('[data-proton-command]').forEach(n=>n.textContent='bash Loki-Mod-Installer-Linux.sh --server '+data.site_url);
  document.querySelectorAll('[data-plus]').forEach(n=>n.hidden=!plus);document.querySelectorAll('[data-vanilla]').forEach(n=>n.hidden=hasMods);document.querySelectorAll('[data-modded]').forEach(n=>n.hidden=!modded);document.querySelectorAll('[data-mods]').forEach(n=>n.hidden=!hasMods);
  setText('mode-label',plus?'Valheim Plus':modded?'BepInEx · Моды':'Ванильный сервер');

  renderDescription();setText('listing-name',data.server_name);
  setText('public-game',data.game||'Ещё не установлена');setText('public-mod',plus?(data.mod?'V+ '+data.mod:'V+ ещё не установлен'):modded?'BepInEx':'Без модов');
  const status=el('public-status');const dot=document.createElement('i');dot.className='dot'+(data.players!==null?' online':'');
  status.replaceChildren(dot,document.createTextNode(data.players!==null?'Очаг горит':data.running?'Мир запущен':'Сервер на привале'));
  setText('public-players',data.players===null?'—':String(data.players));
  renderMaintenance();
  connectAddress=data.address||'';setText('connect-address',connectAddress||'Адрес скоро появится');el('copy-address').disabled=!connectAddress;
  setText('connect-note',connectAddress?'Подключение в Valheim → Присоединиться → по IP.':'Администратор ещё не опубликовал адрес. Загляни чуть позже.');
  const community=el('community-link');
  if(data.community_url&&/^https?:\/\//i.test(data.community_url)){community.href=data.community_url;community.hidden=false;}else{community.hidden=true;community.removeAttribute('href');}
  renderClientMods();
  const mod=el('mod-download');
  if(data.mod&&/^\d+\.\d+\.\d+(?:\.\d+)?$/.test(data.mod)){
   mod.href='https://github.com/Grantapher/ValheimPlus/releases/tag/'+encodeURIComponent(data.mod);mod.textContent='Скачать V+ '+data.mod+' ↗';
   setText('mod-match','На сервере установлен V+ '+data.mod+'. Выбирай клиентский пакет для своей ОС, не UnixServer.zip.');
  }else{mod.href='https://github.com/Grantapher/ValheimPlus/releases';mod.textContent='Релизы мода ↗';setText('mod-match','Версия ещё не определена. Уточни её у администратора перед загрузкой.');}
 }catch{
  setText('public-status','Нет связи с сервером');setText('public-players','—');setText('status-note','Не удалось обновить состояние. Повторим запрос автоматически; ранее показанные версии и адрес могут быть устаревшими.');
 }finally{pending=false;}
}
el('copy-address').addEventListener('click',async()=>{
 if(!connectAddress)return;
 try{await navigator.clipboard.writeText(connectAddress);setText('copy-feedback','Адрес скопирован. До встречи у очага!');}
 catch{setText('copy-feedback','Выдели адрес выше и скопируй вручную — браузер запретил копирование.');const range=document.createRange();range.selectNodeContents(el('connect-address'));const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);}
});
refreshPublic();setInterval(()=>{if(!document.hidden)refreshPublic();},30000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshPublic();});
