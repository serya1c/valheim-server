'use strict';
(() => {
  let access=null, blocked=true, requesting=false, serverRunning=false, generation=0;
  const messages={
    ban:id=>`Заблокировать SteamID ${id}? Этот аккаунт будет запрещён на игровом сервере.`,
    admin:id=>`Назначить SteamID ${id} игровым администратором? Это даёт игровые права и не открывает доступ к веб-панели. После изменения прав переподключитесь к серверу.`,
    unadmin:id=>`Снять игровые права администратора у SteamID ${id}? Доступ к веб-панели не изменится. После изменения прав переподключитесь к серверу.`,
    kick:id=>`Запросить отключение SteamID ${id} через временный бан на 30 секунд? Valheim применяет списки с задержкой до 15 секунд. Постоянный бан не снимается. Ответ панели не подтверждает фактическое отключение.`
  };
  function updateButtons(){
    document.querySelectorAll('[data-player-action], #player-access-apply').forEach(button=>button.disabled=blocked||requesting||!access||Boolean(access.error));
    const unavailable=$('player-access-action').value==='kick'&&!serverRunning;
    $('player-kick-unavailable').hidden=!unavailable;
    if(unavailable)$('player-access-apply').disabled=true;
  }
  function row(id){
    const node=document.createElement('div');node.className='file-row';
    const name=document.createElement('strong');name.textContent=id;name.dataset.i18nSkip='';node.append(name);return node;
  }
  function button(container,label,action,id){
    const node=document.createElement('button');node.type='button';node.textContent=label;node.dataset.playerAction=action;
    node.onclick=()=>apply(action,id);container.append(node);
  }
  function list(target,ids,empty,action,label){
    const container=$(target);container.replaceChildren();
    if(!ids.length){container.textContent=empty;return;}
    ids.forEach(id=>{const node=row(id);button(node,label,action,id);container.append(node);});
  }
  function render(value){
    access=value;
    $('player-access-error').textContent=value?.error||(!value?'Данные доступа игроков пока недоступны':'');
    list('player-admins',value?.admins||[],'Игровых администраторов пока нет','unadmin','Снять права');
    list('player-banned',value?.banned||[],'Заблокированных SteamID пока нет','unban','Снять блокировку');
    $('player-other-admins').textContent=value?.other_admins?`Других записей в списке администраторов: ${value.other_admins}`:'';
    $('player-other-bans').textContent=value?.other_bans?`Других записей в списке блокировок: ${value.other_bans}`:'';
    const kicks=$('player-kicks');kicks.replaceChildren();
    if(!value?.kicks?.length)kicks.textContent='Активных временных блокировок нет';
    (value?.kicks||[]).forEach(kick=>{
      const node=row(kick.steam_id),info=document.createElement('span');
      info.textContent='Снятие не раньше: '+fmtTime(kick.until);node.append(info);
      button(node,'Снять сейчас','unban',kick.steam_id);kicks.append(node);
    });
    updateButtons();
  }
  async function apply(action,id){
    if(blocked||requesting||!access||access.error)return;
    if(action==='kick'&&!serverRunning){$('player-access-message').textContent='Для отключения игрока сервер должен быть запущен';return;}
    const match=/^(?:Steam_)?([0-9]{17})$/.exec(id.trim());
    if(!match){$('player-access-message').textContent='Введите SteamID64: 17 цифр или Steam_ и 17 цифр';return;}
    const steamId=match[1],started=generation;
    requesting=true;updateButtons();
    try{
      if(messages[action]&&!await confirmAction(messages[action](steamId)))return;
      if(started!==generation||!csrf||blocked||access?.error)return;
      const result=await api('/api/players',{action,steam_id:steamId});
      if(started!==generation)return;
      render(result.access);$('player-access-message').textContent=result.message;
    }catch(error){if(started===generation)$('player-access-message').textContent=error.message;}
    finally{if(started===generation){requesting=false;updateButtons();}}
  }
  $('player-access-form').onsubmit=event=>{event.preventDefault();apply($('player-access-action').value,$('player-steam-id').value);};
  $('player-access-action').onchange=updateButtons;
  window.addEventListener('hearth-status',event=>{blocked=Boolean(event.detail.busy||event.detail.closing);serverRunning=Boolean(event.detail.running);render(event.detail.player_access);});
  window.addEventListener('hearth-language',()=>{if(access)render(access);});
  window.addEventListener('hearth-logout',()=>{
    generation++;access=null;blocked=true;requesting=false;serverRunning=false;
    $('player-steam-id').value='';$('player-access-action').value='ban';$('player-access-message').textContent='';
    render(null);
  });
})();
