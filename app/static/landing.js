'use strict';
const el=id=>document.getElementById(id);
let connectAddress='',pending=false;
function setText(id,value){el(id).textContent=value;}
async function refreshPublic(){
 if(pending)return;pending=true;
 try{
  const response=await fetch('/api/public',{cache:'no-store'});
  if(!response.ok)throw new Error('Unavailable');
  const data=await response.json();
  document.querySelectorAll('[data-server-name]').forEach(node=>{
   // Preserve the small navigation subtitle without using HTML from settings.
   if(node.querySelector('small')){node.firstChild.textContent=data.title;}else node.textContent=data.title;
  });
  document.title=data.title+' — сервер Valheim с Valheim Plus | Подключение';
  setText('server-description',data.description);setText('listing-name',data.server_name);
  setText('public-game',data.game||'Ещё не установлена');setText('public-mod',data.mod||'Ещё не установлен');
  const status=el('public-status');const dot=document.createElement('i');dot.className='dot'+(data.players!==null?' online':'');
  status.replaceChildren(dot,document.createTextNode(data.players!==null?'Очаг горит':data.running?'Мир запущен':'Сервер на привале'));
  setText('public-players',data.players===null?'—':String(data.players));
  setText('status-note',data.players!==null?'Состояние обновляется каждые 30 секунд.':data.running?'Процесс сервера запущен. Число игроков пока неизвестно: сервер не отвечает на запрос статистики.':'Сервер сейчас остановлен. Инструкция и адрес остаются доступными.');
  connectAddress=data.address||'';setText('connect-address',connectAddress||'Адрес скоро появится');el('copy-address').disabled=!connectAddress;
  setText('connect-note',connectAddress?'Подключение в Valheim → Присоединиться → по IP.':'Администратор ещё не опубликовал адрес. Загляни чуть позже.');
  const community=el('community-link');
  if(data.community_url&&/^https?:\/\//i.test(data.community_url)){community.href=data.community_url;community.hidden=false;}else{community.hidden=true;community.removeAttribute('href');}
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
