"use strict";
let operationsState=null, discordLoaded=false;
const operationNames={restart:'Перезапуск',stop:'Остановка',backup:'Резервная копия',install:'Обновление игры и мода'};
const taskStates={pending:'Ожидает выполнения',running:'Выполняется',done:'Завершено',error:'Ошибка',cancelled:'Отменено',interrupted:'Прервано перезапуском панели. Проверьте журнал перед повтором.'};
function renderOperations(o){
 operationsState=o;
 const r=o.release;
 $('panel-release').textContent=I18n.t('Текущая версия')+': '+r.current+' · '+(r.latest?I18n.t('Последний релиз')+': '+r.latest:I18n.t('Проверка ещё не выполнялась'))+(r.available?' · '+I18n.t('Доступно обновление'):'');
 if(r.error)$('panel-release').textContent+=' · '+I18n.t(r.error);
 $('panel-release-link').hidden=!r.url;if(r.url)$('panel-release-link').href=r.url;
 const t=o.maintenance;
 $('maintenance-status').textContent=t?I18n.t(operationNames[t.operation])+' · '+fmtTime(t.at)+' · '+I18n.t(taskStates[t.state])+(t.wait_empty?' · '+I18n.t('Дождаться пустого сервера'):''):I18n.t('Нет запланированных задач');
 $('maintenance-cancel').disabled=!t||t.state!=='pending';
 if(!discordLoaded){document.querySelectorAll('[data-discord]').forEach(n=>n.checked=o.discord.events.includes(n.dataset.discord));discordLoaded=true;}
 $('discord-status').textContent=I18n.t(o.discord.configured?'Webhook сохранён':'Webhook не настроен')+(o.discord.delivery?' · '+I18n.t(o.discord.delivery):'');
 $('discord-test').disabled=!o.discord.configured;
}
window.addEventListener('hearth-status',e=>renderOperations(e.detail.operations));
window.addEventListener('hearth-language',()=>{if(operationsState)renderOperations(operationsState);});
window.addEventListener('hearth-logout',()=>{discordLoaded=false;operationsState=null;$('discord-url').value='';$('discord-remove').checked=false;});
async function operationsCommand(data){try{const o=await api('/api/operations',data);renderOperations(o);$('operations-message').textContent=({discord:'Уведомления сохранены',schedule:'Обслуживание запланировано',cancel:'Задача отменена',test:'Проверочное уведомление в очереди'})[data.command];return true;}catch(e){$('operations-message').textContent=e.message;return false;}}
$('maintenance-form').onsubmit=async e=>{e.preventDefault();if(!await confirmAction('Запланировать обслуживание? При выключенном ожидании пустого сервера игроки могут быть отключены.'))return;await operationsCommand({command:'schedule',operation:$('maintenance-operation').value,at:new Date($('maintenance-at').value).getTime()/1000,wait_empty:$('maintenance-empty').checked});};
$('maintenance-cancel').onclick=()=>operationsCommand({command:'cancel'});
$('discord-form').onsubmit=async e=>{e.preventDefault();if(await operationsCommand({command:'discord',url:$('discord-url').value.trim(),remove:$('discord-remove').checked,events:[...document.querySelectorAll('[data-discord]:checked')].map(n=>n.dataset.discord)})){$('discord-url').value='';$('discord-remove').checked=false;}};
$('discord-test').onclick=()=>operationsCommand({command:'test'});
$('panel-check').onclick=async()=>{try{await api('/api/action',{action:'check_panel'});await refresh();}catch(e){$('operations-message').textContent=e.message;}};
$('panel-compose').onchange=()=>{$('panel-command').textContent=$('panel-compose').value==='second'?'docker compose -f compose.second.yaml -p valheim-second up -d --build':'docker compose up -d --build';};
$('panel-command-copy').onclick=async()=>{try{await navigator.clipboard.writeText($('panel-command').textContent);$('operations-message').textContent='Команда скопирована';}catch{$('operations-message').textContent='Выделите и скопируйте команду вручную';}};
const nextTime=new Date(Date.now()+60000);nextTime.setMinutes(nextTime.getMinutes()-nextTime.getTimezoneOffset());$('maintenance-at').value=nextTime.toISOString().slice(0,16);
