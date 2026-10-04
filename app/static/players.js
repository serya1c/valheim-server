'use strict';
(() => {
  let access=null, blocked=true, requesting=false, serverRunning=false, generation=0;
  const messages={
    ban:id=>`Заблокировать SteamID ${id}? Этот аккаунт будет запрещён на игровом сервере.`,
    admin:id=>`Назначить SteamID ${id} игровым администратором? Это даёт игровые права и не открывает доступ к веб-панели. После изменения прав переподключитесь к серверу.`,
    unadmin:id=>`Снять игровые права администратора у SteamID ${id}? Доступ к веб-панели не изменится. После изменения прав переподключитесь к серверу.`,
    kick:id=>`Запросить отключение SteamID ${id} через временный бан на 30 секунд? Valheim применяет списки с задержкой до 15 секунд. Постоянный бан не снимается. Ответ панели не подтверждает фактическое отключение.`
  };
  const labels={ban:'Бан игрока',unban:'Снятие бана',admin:'Выдача игровых прав администратора',unadmin:'Снятие игровых прав администратора',kick:'Запрос отключения игрока',profile:'Сохранение заметки об игроке',expiry:'Истечение временного бана'};
  function updateButtons(){
    document.querySelectorAll('[data-player-action], [data-player-profile], #player-access-apply, #player-profile-save').forEach(button=>button.disabled=blocked||requesting||!access||Boolean(access.error));
    if($('player-ban-options'))$('player-ban-options').hidden=$('player-access-action').value!=='ban';
    const unavailable=$('player-access-action').value==='kick'&&!serverRunning;
    $('player-kick-unavailable').hidden=!unavailable;
    if(unavailable)$('player-access-apply').disabled=true;
  }
  function row(id){
    const node=document.createElement('div');node.className='file-row';
    const name=document.createElement('strong'),alias=access?.profiles?.[id]?.alias;
    name.textContent=alias?`${alias} · ${id}`:id;name.dataset.i18nSkip='';node.append(name);return node;
  }
  function privateText(container,text){const node=document.createElement('p');node.className='player-private-text tiny';node.textContent=text;node.dataset.i18nSkip='';container.append(node);}
  function editProfile(id){
    const profile=access?.profiles?.[id]||{};
    $('player-profile-steam-id').value=id;$('player-profile-alias').value=profile.alias||'';$('player-profile-notes').value=profile.notes||'';
    $('player-profile-message').textContent='';$('player-profile-alias').focus();
  }
  function profileButton(container,id){
    const node=document.createElement('button');node.type='button';node.textContent='Имя и заметка';node.dataset.playerProfile='';node.onclick=()=>editProfile(id);container.append(node);
  }
  function button(container,label,action,id){
    const node=document.createElement('button');node.type='button';node.textContent=label;node.dataset.playerAction=action;
    node.onclick=()=>apply(action,id);container.append(node);
  }
  function list(target,ids,empty,action,label){
    const container=$(target);container.replaceChildren();
    if(!ids.length){container.textContent=empty;return;}
    ids.forEach(id=>{const node=row(id);const reason=access?.ban_details?.[id]?.reason;if(action==='unban'&&reason)privateText(node,reason);button(node,label,action,id);profileButton(node,id);container.append(node);});
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
    const timed=$('player-timed-bans');timed.replaceChildren();
    if(!value?.timed_bans?.length)timed.textContent='Временных банов пока нет';
    (value?.timed_bans||[]).forEach(ban=>{
      const node=row(ban.steam_id),info=document.createElement('span');info.textContent='Окончание бана: '+fmtTime(ban.until);node.append(info);
      if(ban.reason)privateText(node,ban.reason);
      button(node,'Снять блокировку','unban',ban.steam_id);profileButton(node,ban.steam_id);timed.append(node);
    });
    const profiles=$('player-profiles');profiles.replaceChildren();
    if(!Object.keys(value?.profiles||{}).length)profiles.textContent='Сохранённых заметок пока нет';
    Object.keys(value?.profiles||{}).sort().forEach(id=>{const node=row(id);if(value.profiles[id].notes)privateText(node,value.profiles[id].notes);profileButton(node,id);profiles.append(node);});
    const history=$('player-history');history.replaceChildren();
    if(!value?.history?.length)history.textContent='История модерации пока пуста';
    (value?.history||[]).forEach(item=>{
      const node=row(item.steam_id),info=document.createElement('span');info.textContent=fmtTime(item.at)+' · '+(labels[item.action]||item.action);node.append(info);
      if(item.until){const expiry=document.createElement('span');expiry.textContent='Окончание бана: '+fmtTime(item.until);node.append(expiry);}
      if(item.reason)privateText(node,item.reason);profileButton(node,item.steam_id);history.append(node);
    });
    updateButtons();
  }
  async function apply(action,id,options={}){
    if(blocked||requesting||!access||access.error)return;
    if(action==='kick'&&!serverRunning){$('player-access-message').textContent='Для отключения игрока сервер должен быть запущен';return;}
    const match=/^(?:Steam_)?([0-9]{17})$/.exec(id.trim());
    if(!match){$('player-access-message').textContent='Введите SteamID64: 17 цифр или Steam_ и 17 цифр';return;}
    const steamId=match[1],started=generation;
    requesting=true;updateButtons();
    try{
      let prompt=messages[action]?.(steamId);
      if(action==='ban'&&options.duration_hours!=null)prompt=`Заблокировать SteamID ${steamId} на ${options.duration_hours} ч? Бан будет снят автоматически после окончания срока.`;
      if(prompt&&options.reason)prompt+='\nПричина бана: '+options.reason;
      if(prompt&&!await confirmAction(prompt))return;
      if(started!==generation||!csrf||blocked||access?.error)return;
      const result=await api('/api/players',{action,steam_id:steamId,...options});
      if(started!==generation)return;
      render(result.access);$('player-access-message').textContent=result.message;
    }catch(error){if(started===generation)$('player-access-message').textContent=error.message;}
    finally{if(started===generation){requesting=false;updateButtons();}}
  }
  $('player-access-form').onsubmit=event=>{
    event.preventDefault();const action=$('player-access-action').value,options={};
    if(action==='ban'){
      options.reason=$('player-ban-reason').value;
      const hours=$('player-ban-hours').value;if(hours!=='')options.duration_hours=Number(hours);
    }
    apply(action,$('player-steam-id').value,options);
  };
  $('player-profile-form').onsubmit=async event=>{
    event.preventDefault();if(blocked||requesting||!access||access.error)return;
    const match=/^(?:Steam_)?([0-9]{17})$/.exec($('player-profile-steam-id').value.trim());
    if(!match){$('player-profile-message').textContent='Введите SteamID64: 17 цифр или Steam_ и 17 цифр';return;}
    const started=generation;requesting=true;updateButtons();
    try{
      const result=await api('/api/players',{action:'profile',steam_id:match[1],alias:$('player-profile-alias').value,notes:$('player-profile-notes').value});
      if(started!==generation)return;render(result.access);$('player-profile-message').textContent=result.message;
    }catch(error){if(started===generation)$('player-profile-message').textContent=error.message;}
    finally{if(started===generation){requesting=false;updateButtons();}}
  };
  $('player-access-action').onchange=updateButtons;
  window.addEventListener('hearth-status',event=>{blocked=Boolean(event.detail.busy||event.detail.closing);serverRunning=Boolean(event.detail.running);render(event.detail.player_access);});
  window.addEventListener('hearth-language',()=>{if(access)render(access);});
  window.addEventListener('hearth-logout',()=>{
    generation++;access=null;blocked=true;requesting=false;serverRunning=false;
    $('player-steam-id').value='';$('player-access-action').value='ban';$('player-access-message').textContent='';
    ['player-ban-reason','player-ban-hours','player-profile-steam-id','player-profile-alias','player-profile-notes'].forEach(id=>$(id).value='');$('player-profile-message').textContent='';
    render(null);
  });
})();
