"use strict";
let operationsState=null, discordLoaded=false, routinesBusy=false, operationsRequest=false, operationsGeneration=0;
const operationNames={restart:'Перезапуск',stop:'Остановка',backup:'Резервная копия',install:'Обновление игры и мода'};
const taskStates={pending:'Ожидает выполнения',running:'Выполняется',done:'Завершено',error:'Ошибка',cancelled:'Отменено',interrupted:'Прервано перезапуском панели. Проверьте журнал перед повтором.',scheduled:'По расписанию',skipped:'Пропущено'};
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
 renderRoutines(o);
 setOperationControls();
}
function setOperationControls(){
 const locked=routinesBusy||operationsRequest;
 $('maintenance')?.querySelectorAll('button').forEach(button=>button.disabled=locked);
 $('maintenance-cancel').disabled=locked||operationsState?.maintenance?.state!=='pending';
 $('discord-test').disabled=locked||!operationsState?.discord?.configured;
 $('panel-check').disabled=locked;
}
function beginOperationsRequest(){
 if(operationsRequest)return null;
 operationsRequest=true;setOperationControls();return operationsGeneration;
}
function endOperationsRequest(generation){
 if(generation===operationsGeneration){operationsRequest=false;setOperationControls();}
}
window.addEventListener('hearth-status',e=>{routinesBusy=Boolean(e.detail.busy);renderOperations(e.detail.operations);});
window.addEventListener('hearth-language',()=>{if(operationsState)renderOperations(operationsState);});
window.addEventListener('hearth-logout',()=>{operationsGeneration++;operationsRequest=false;routinesBusy=false;discordLoaded=false;operationsState=null;$('discord-url').value='';$('discord-remove').checked=false;$('operations-message').textContent='';setOperationControls();});
async function operationsCommand(data){
 const generation=beginOperationsRequest();if(generation===null)return false;
 try{
  const o=await api('/api/operations',data);
  if(generation!==operationsGeneration)return false;
  renderOperations(o);$('operations-message').textContent=({discord:'Уведомления сохранены',schedule:'Обслуживание запланировано',cancel:'Задача отменена',test:'Проверочное уведомление в очереди',routine_save:'Расписание сохранено',routine_toggle:'Состояние расписания изменено',routine_remove:'Расписание удалено'})[data.command];return true;
 }catch(e){if(generation===operationsGeneration)$('operations-message').textContent=e.message;return false;}
 finally{endOperationsRequest(generation);}
}
$('maintenance-form').onsubmit=async e=>{e.preventDefault();if(!await confirmAction('Запланировать обслуживание? При выключенном ожидании пустого сервера игроки могут быть отключены.'))return;await operationsCommand({command:'schedule',operation:$('maintenance-operation').value,at:new Date($('maintenance-at').value).getTime()/1000,wait_empty:$('maintenance-empty').checked});};
$('maintenance-cancel').onclick=()=>operationsCommand({command:'cancel'});
$('discord-form').onsubmit=async e=>{e.preventDefault();const data={command:'discord',url:$('discord-url').value.trim(),remove:$('discord-remove').checked,events:[...document.querySelectorAll('[data-discord]:checked')].map(n=>n.dataset.discord)};if(await operationsCommand(data)){if($('discord-url').value.trim()===data.url)$('discord-url').value='';if($('discord-remove').checked===data.remove)$('discord-remove').checked=false;}};
$('discord-test').onclick=()=>operationsCommand({command:'test'});
$('panel-check').onclick=async()=>{const generation=beginOperationsRequest();if(generation===null)return;try{await api('/api/action',{action:'check_panel'});if(generation===operationsGeneration)await refresh();}catch(e){if(generation===operationsGeneration)$('operations-message').textContent=e.message;}finally{endOperationsRequest(generation);}};
$('panel-compose').onchange=()=>{$('panel-command').textContent=$('panel-compose').value==='second'?'docker compose -f compose.second.yaml -p valheim-second up -d --build':'docker compose up -d --build';};
$('panel-command-copy').onclick=async()=>{const generation=operationsGeneration;try{await navigator.clipboard.writeText($('panel-command').textContent);if(generation===operationsGeneration)$('operations-message').textContent='Команда скопирована';}catch{if(generation===operationsGeneration)$('operations-message').textContent='Выделите и скопируйте команду вручную';}};
const nextTime=new Date(Date.now()+60000);nextTime.setMinutes(nextTime.getMinutes()-nextTime.getTimezoneOffset());$('maintenance-at').value=nextTime.toISOString().slice(0,16);

const routineDays=['Понедельник','Вторник','Среда','Четверг','Пятница','Суббота','Воскресенье'];
const routineReasons={deadline:'Истекло окно ожидания',missed:'Пропущено во время остановки панели',panel_restart:'Панель перезапущена',overlap:'Предыдущий запуск ещё не завершён',operation:'Ошибка операции',changed:'Расписание изменено',manual:'Отменено вручную'};
function routineTime(at,zone){
 try{return new Intl.DateTimeFormat(I18n.locale,{timeZone:zone,dateStyle:'short',timeStyle:'short'}).format(new Date(at*1000));}
 catch{return fmtTime(at);}
}
function routineButton(label,handler){const button=document.createElement('button');button.type='button';button.textContent=I18n.t(label);button.disabled=routinesBusy||operationsRequest;button.onclick=handler;return button;}
function renderRoutines(o){
 if(!$('routine-list'))return;
 const fragment=document.createDocumentFragment();
 for(const routine of o.routines||[]){
  const row=document.createElement('div');row.className='file-row';
  const description=document.createElement('div');
  const title=document.createElement('strong');title.textContent=I18n.t(operationNames[routine.operation])+' · '+I18n.t(routine.frequency==='daily'?'Ежедневно':'Еженедельно');description.append(title);
  const details=document.createElement('p');details.className='tiny';
  const time=document.createElement('span');time.dataset.i18nSkip='';time.textContent=routine.time+' · '+routine.timezone;details.append(time);
  if(routine.frequency==='weekly')details.append(document.createTextNode(' · '+routine.weekdays.map(d=>I18n.t(routineDays[d])).join(', ')));
  details.append(document.createTextNode(' · '+I18n.t(routine.enabled?'Расписание включено':'На паузе')+' · '+I18n.t('Окно ожидания')+': '+routine.max_wait_minutes+' '+I18n.t('минут')));
  description.append(details);row.append(description);
  const toolbar=document.createElement('div');toolbar.className='toolbar';
  toolbar.append(routineButton('Редактировать',()=>editRoutine(routine)),routineButton(routine.enabled?'Приостановить':'Возобновить',()=>operationsCommand({command:'routine_toggle',id:routine.id,enabled:!routine.enabled})),routineButton('Удалить',async()=>{if(await confirmAction('Удалить расписание? Ожидающий запуск будет отменён.'))await operationsCommand({command:'routine_remove',id:routine.id});}));
  row.append(toolbar);fragment.append(row);
 }
 if(!(o.routines||[]).length){const p=document.createElement('p');p.className='muted';p.textContent=I18n.t('Расписаний пока нет');fragment.append(p);}
 $('routine-list').replaceChildren(fragment);
 table('routine-upcoming',o.upcoming||[],(row,item)=>{cell(row,routineTime(item.at,item.timezone));cell(row,I18n.t(operationNames[item.operation]));cell(row,item.timezone,true);cell(row,I18n.t(taskStates[item.state]||item.state));},4);
 table('routine-history',o.history||[],(row,item)=>{cell(row,fmtTime(item.at));cell(row,I18n.t(operationNames[item.operation]));cell(row,I18n.t(taskStates[item.state]||item.state)+(item.reason?' · '+I18n.t(routineReasons[item.reason]||item.reason):''));},3);
 $('routine-form').querySelectorAll('button').forEach(button=>button.disabled=routinesBusy||operationsRequest);
}
function editRoutine(routine){
 $('routine-id').value=routine.id;$('routine-operation').value=routine.operation;$('routine-frequency').value=routine.frequency;
 $('routine-time').value=routine.time;$('routine-timezone').value=routine.timezone;$('routine-max-wait').value=routine.max_wait_minutes;$('routine-enabled').checked=routine.enabled;
 document.querySelectorAll('[data-routine-day]').forEach(box=>box.checked=routine.weekdays.includes(Number(box.dataset.routineDay)));
 $('routine-weekdays').hidden=routine.frequency!=='weekly';$('routine-form').scrollIntoView({block:'nearest'});
}
function resetRoutineForm(){
 $('routine-form').reset();$('routine-id').value='';$('routine-weekdays').hidden=true;
 try{$('routine-timezone').value=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';}catch{$('routine-timezone').value='UTC';}
}
if($('routine-form')){
 resetRoutineForm();
 $('routine-frequency').onchange=()=>{$('routine-weekdays').hidden=$('routine-frequency').value!=='weekly';};
 $('routine-reset').onclick=resetRoutineForm;
 $('routine-form').onsubmit=async event=>{
  event.preventDefault();
  const data={command:'routine_save',operation:$('routine-operation').value,frequency:$('routine-frequency').value,time:$('routine-time').value,timezone:$('routine-timezone').value.trim(),weekdays:[...document.querySelectorAll('[data-routine-day]:checked')].map(box=>Number(box.dataset.routineDay)),enabled:$('routine-enabled').checked,max_wait_minutes:Number($('routine-max-wait').value)};
  if($('routine-id').value)data.id=$('routine-id').value;
  if(await operationsCommand(data)){
   const unchanged=$('routine-id').value===(data.id||'')&&$('routine-operation').value===data.operation&&$('routine-frequency').value===data.frequency&&$('routine-time').value===data.time&&$('routine-timezone').value.trim()===data.timezone&&Number($('routine-max-wait').value)===data.max_wait_minutes&&$('routine-enabled').checked===data.enabled&&JSON.stringify([...document.querySelectorAll('[data-routine-day]:checked')].map(box=>Number(box.dataset.routineDay)))===JSON.stringify(data.weekdays);
   if(unchanged)resetRoutineForm();
  }
 };
 window.addEventListener('hearth-logout',resetRoutineForm);
}
