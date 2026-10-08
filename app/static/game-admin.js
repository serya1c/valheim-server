'use strict';
(() => {
  if (!$('game-admin')) return;
  const targetActions=new Set(['TeleportToPlayer','SummonPlayer','GodPlayer','HealPlayer','RestoreStaminaPlayer','ClearEffectsPlayer','SetRole']);
  const roles={None:'Игрок',Moderator:'Модератор',Builder:'Строитель',Owner:'Владелец'};
  const actionNames={TeleportMap:'К координатам',TeleportToPlayer:'К целевому игроку',SummonPlayer:'Призвать целевого игрока',GodSelf:'Бог себе',GodPlayer:'Бог цели',SpawnItem:'Создать предметы',SpawnMob:'Создать существ',Flatten:'Выровнять землю',HammerToggle:'Супермолот',HammerStrike:'Ударить супермолотом',RaiseTerrain:'Поднять землю',LowerTerrain:'Опустить землю',FlySelf:'Полёт',UndoTerrain:'Отменить изменение земли',CleanupSpawn:'Очистить последнюю порцию спавна',ReturnTeleport:'Вернуться после телепорта',TeleportSaved:'К сохранённой точке',HealPlayer:'Вылечить цель',RestoreStaminaPlayer:'Восстановить выносливость цели',ClearEffectsPlayer:'Снять эффекты с цели',BuildToggle:'Строительный режим',RepairArea:'Отремонтировать рядом',SetRole:'Назначить роль мода'};
  const liveActorActions=new Set(['TeleportMap','TeleportToPlayer','SummonPlayer','GodSelf','SpawnItem','SpawnMob','Flatten','HammerToggle','HammerStrike','RaiseTerrain','LowerTerrain','FlySelf','UndoTerrain','CleanupSpawn','ReturnTeleport','TeleportSaved','BuildToggle','RepairArea']);
  let view=null,busy=true,closing=false,loading=false,posting=false,confirming=false,pending=null,generation=0,lastLoad=0,resultTimer=null,lastMessage='',lastMessageEn='',lastError=false;
  const buttons=[],fields={},catalogSignatures={};

  function node(tag,value='',literal=false,className=''){
    const item=document.createElement(tag);item.textContent=value;
    if(literal)item.dataset.i18nSkip='';if(className)item.className=className;return item;
  }
  function field(parent,key,label,options={}){
    const host=node('label',label),input=document.createElement(options.type==='select'?'select':'input');
    input.id='game-admin-'+key;
    if(options.type!=='select')input.type=options.type||'text';
    for(const property of ['min','max','step','maxLength','value'])if(options[property]!==undefined)input[property]=options[property];
    if(options.options)for(const [value,title] of options.options){const option=node('option',title);option.value=value;input.append(option);}
    if(options.required)input.required=true;
    if(options.literal)input.dataset.i18nSkip='';
    input.addEventListener('input',controls);input.addEventListener('change',controls);
    host.append(input);parent.append(host);fields[key]=input;return input;
  }
  function card(title,description){
    const item=node('article','',false,'card');item.append(node('h3',title),node('p',description,false,'tiny'));
    const content=node('div');item.append(content);$('game-admin-actions').append(item);return content;
  }
  function toolbar(parent){const item=node('div','',false,'toolbar');parent.append(item);return item;}
  function button(parent,label,action,permission,values=()=>({}),inputKeys=[]){
    const item=node('button',label);item.type='button';
    item.dataset.gameAdminAction=action;item.dataset.gameAdminGroup=permission;
    const spec={item,label,action,values,inputKeys};buttons.push(spec);
    item.onclick=()=>send(spec);parent.append(item);return item;
  }
  function number(key){return fields[key].valueAsNumber;}
  function build(){
    let content=card('Перемещение','Телепорты и возврат относятся к выбранному выполняющему игроку. Для карты укажите X и Z; высоту найдёт игра.');
    const coordinates=node('div','',false,'game-admin-coordinates');content.append(coordinates);
    field(coordinates,'map-x','X',{type:'number',min:-10500,max:10500,step:'any',value:0,required:true});
    field(coordinates,'map-z','Z',{type:'number',min:-10500,max:10500,step:'any',value:0,required:true});
    let actions=toolbar(content);
    button(actions,'К координатам','TeleportMap','travel',()=>({x:number('map-x'),z:number('map-z')}),['map-x','map-z']);
    button(actions,'К целевому игроку','TeleportToPlayer','travel');
    button(actions,'Призвать целевого игрока','SummonPlayer','help');
    button(actions,'Вернуться после телепорта','ReturnTeleport','travel');

    content=card('Сохранённые точки','Точки хранятся на клиенте выполняющего игрока и относятся к текущему миру. Создавайте и удаляйте их в меню F8.');
    field(content,'point','Точка выполняющего игрока',{type:'select',literal:true});
    const pointInfo=node('p','',true,'tiny');pointInfo.id='game-admin-point-info';content.append(pointInfo);
    button(toolbar(content),'К сохранённой точке','TeleportSaved','travel',()=>({point_id:fields.point.value}));
    fields.point.addEventListener('change',renderPointInfo);

    content=card('Помощь игрокам','Помощь использует выбранную цель. Полёт и режим бога для себя относятся к выполняющему игроку.');
    actions=toolbar(content);
    button(actions,'Бог себе: включить','GodSelf','help',()=>({enabled:true}));
    button(actions,'Бог себе: выключить','GodSelf','help',()=>({enabled:false}));
    button(actions,'Полёт: включить','FlySelf','travel',()=>({enabled:true}));
    button(actions,'Полёт: выключить','FlySelf','travel',()=>({enabled:false}));
    actions=toolbar(content);
    button(actions,'Вылечить цель','HealPlayer','help');
    button(actions,'Восстановить выносливость цели','RestoreStaminaPlayer','help');
    button(actions,'Снять эффекты с цели','ClearEffectsPlayer','help');
    button(actions,'Бог цели: включить','GodPlayer','help',()=>({enabled:true}));
    button(actions,'Бог цели: выключить','GodPlayer','help',()=>({enabled:false}));

    for(const [kind,title,description,action,maximum] of [
      ['item','Предметы','Предметы появятся рядом с выполняющим игроком. Количество делится на допустимые игровые стопки.','SpawnItem',500],
      ['mob','Существа','Существа появятся рядом с выполняющим игроком. Проверьте выбранный prefab и количество.','SpawnMob',20]]){
      content=card(title,description);
      const prefab=field(content,kind+'-prefab','Объект из игрового каталога',{maxLength:160,required:true});
      const list=document.createElement('datalist');list.id='game-admin-'+kind+'-catalog';content.append(list);prefab.setAttribute('list',list.id);
      field(content,kind+'-count','Количество',{type:'number',min:1,max:maximum,step:1,value:1,required:true});
      button(toolbar(content),kind==='item'?'Создать предметы':'Создать существ',action,'spawn',()=>({prefab:prefab.value.trim(),count:number(kind+'-count')}),[kind+'-prefab',kind+'-count']);
    }

    content=card('Земля','Изменения применяются вокруг выполняющего игрока. Отмена относится к его последней операции с землёй; более поздние изменения могут помешать отмене.');
    field(content,'terrain-radius','Радиус · м',{type:'number',min:1,max:40,step:'any',value:5,required:true});
    field(content,'terrain-height','Высота изменения · м',{type:'number',min:.1,max:8,step:.1,value:1,required:true});
    const terrain=()=>({radius:number('terrain-radius'),height:number('terrain-height')});
    actions=toolbar(content);
    button(actions,'Выровнять землю','Flatten','terrain',terrain,['terrain-radius','terrain-height']);
    button(actions,'Поднять землю','RaiseTerrain','terrain',terrain,['terrain-radius','terrain-height']);
    button(actions,'Опустить землю','LowerTerrain','terrain',terrain,['terrain-radius','terrain-height']);
    button(actions,'Отменить изменение земли','UndoTerrain','terrain');

    content=card('Супермолот','Для удара выполняющему игроку нужно держать супермолот администратора. Удар затрагивает выбранные категории рядом с персонажем.');
    field(content,'hammer-radius','Радиус удара · м',{type:'number',min:1,max:40,step:'any',value:5,required:true});
    const toggles=node('div','',false,'game-admin-toggles');content.append(toggles);
    for(const [mask,title] of [[1,'Существа'],[2,'Деревья'],[4,'Руда'],[8,'Постройки']]){
      const label=node('label'),input=document.createElement('input');input.type='checkbox';input.checked=true;input.value=mask;input.dataset.gameAdminHammer='';input.onchange=controls;label.append(input,node('span',title));toggles.append(label);
    }
    const hammer=enabled=>({enabled,radius:number('hammer-radius'),hammer_targets:[...toggles.querySelectorAll('input:checked')].reduce((mask,input)=>mask|Number(input.value),0)});
    actions=toolbar(content);
    button(actions,'Молот: включить','HammerToggle','hammer',()=>hammer(true),['hammer-radius']);
    button(actions,'Молот: выключить','HammerToggle','hammer',()=>hammer(false),['hammer-radius']);
    button(actions,'Ударить супермолотом','HammerStrike','hammer',()=>hammer(true),['hammer-radius']);

    content=card('Строительство и очистка','Строительный режим и ремонт действуют вокруг выполняющего игрока. Очистка удаляет только последнюю порцию объектов, созданную им через этот мод.');
    field(content,'repair-radius','Радиус ремонта · м',{type:'number',min:1,max:40,step:'any',value:5,required:true});
    actions=toolbar(content);
    button(actions,'Строительство: включить','BuildToggle','build',()=>({enabled:true}));
    button(actions,'Строительство: выключить','BuildToggle','build',()=>({enabled:false}));
    button(actions,'Отремонтировать рядом','RepairArea','build',()=>({radius:number('repair-radius')}),['repair-radius']);
    button(actions,'Очистить последнюю порцию спавна','CleanupSpawn','spawn');

    content=card('Назначить роль мода','Администратор Hearth назначает роль меню F8 выбранному целевому игроку. Роль хранится на сервере; владельцев назначают через adminlist.txt.');
    field(content,'assigned-role','Новая роль',{type:'select',options:[['None','Игрок'],['Moderator','Модератор'],['Builder','Строитель']]});
    button(toolbar(content),'Назначить выбранную роль','SetRole','roles',()=>({role:fields['assigned-role'].value}));
  }

  function actor(){return view?.players?.find(player=>player.steam_id===$('game-admin-executor').value);}
  function target(){return view?.players?.find(player=>player.steam_id===$('game-admin-target').value);}
  function reason(spec){
    if(!csrf)return 'Войдите в веб-панель';
    if(busy||closing)return 'Дождитесь завершения обслуживания';
    if(posting||pending||confirming)return 'Дождитесь результата предыдущей игровой команды';
    if(!view?.available)return view?.message||'Игровой мост ещё не готов';
    const player=actor();
    if(!player)return 'Выберите выполняющего игрока';
    if(!player.ready)return 'У исполнителя нет совместимого клиентского админ-мода';
    if(liveActorActions.has(spec.action)&&!player.alive)return 'Персонаж исполнителя должен быть жив и находиться в мире';
    if(targetActions.has(spec.action)&&!target())return 'Выберите целевого игрока';
    if(spec.action==='SetRole'&&target()?.role==='Owner')return 'Владельцы из adminlist.txt сохраняют полный доступ.';
    if(spec.action==='ReturnTeleport'&&!player.can_return)return 'У исполнителя нет точки возврата';
    if(spec.action==='TeleportSaved'&&(!player.points_ready||!fields.point.value))return 'Дождитесь точек клиента и выберите точку';
    if(spec.action==='HammerStrike'&&!player.hammer)return 'Сначала включите супермолот';
    return '';
  }
  function controls(){
    for(const spec of buttons){const unavailable=reason(spec);spec.item.disabled=Boolean(unavailable);spec.item.title=unavailable;}
    $('game-admin-reload').disabled=loading||posting||closing||!csrf;
  }
  function options(select,players){
    const selected=select.value,fragment=document.createDocumentFragment();
    const empty=node('option',I18n.t('Выберите игрока'),true);empty.value='';fragment.append(empty);
    for(const player of players){
      const option=node('option',(player.name||'—')+' · '+player.steam_id+' · '+I18n.t(roles[player.role]||'Игрок')+(player.ready?'':' · '+I18n.t('Без совместимого мода')),true);
      option.value=player.steam_id;fragment.append(option);
    }
    if(selected&&!players.some(player=>player.steam_id===selected)){
      const missing=node('option',selected+' · '+I18n.t('Игрок отключился'),true);missing.value=selected;fragment.append(missing);
    }
    select.replaceChildren(fragment);select.value=selected;
  }
  function renderPointInfo(){
    const point=actor()?.points?.find(item=>item.id===fields.point.value);
    $('game-admin-point-info').textContent=point?[point.x,point.y,point.z].map(value=>Number(value).toFixed(1)).join(' / '):'';
  }
  function renderPoints(){
    const selected=fields.point.value,player=actor();
    const empty=node('option',I18n.t(player?.points_ready?'Выберите сохранённую точку':'Ожидаем точки клиента'),true);empty.value='';
    fields.point.replaceChildren(empty);
    for(const point of player?.points||[]){if(!/^[a-f0-9]{32}$/.test(point.id))continue;const option=node('option',point.name||point.id,true);option.value=point.id;fields.point.append(option);}
    fields.point.value=selected;renderPointInfo();
  }
  function renderCatalog(kind,entries){
    const signature=I18n.language+JSON.stringify(entries);
    if(catalogSignatures[kind]===signature)return;catalogSignatures[kind]=signature;
    const fragment=document.createDocumentFragment();
    for(const entry of entries){const option=node('option','',true);option.value=entry.prefab;option.label=(I18n.language==='en'?entry.name_en||entry.name:entry.name)||entry.prefab;fragment.append(option);}
    $('game-admin-'+kind+'-catalog').replaceChildren(fragment);
  }
  function roleInfo(){
    const player=actor(),host=$('game-admin-role');host.replaceChildren();
    if(player){
      host.append(node('span','Роль исполнителя: '),node('strong',roles[player.role]||'Игрок'),node('span',player.alive?' · Персонаж жив':' · Персонаж не в мире'));
      for(const [key,title] of [['god','Бог себе'],['flying','Полёт'],['building','Строительный режим'],['hammer','Супермолот']])if(player[key])host.append(node('span',' · '),node('span',title));
    }
    renderPoints();controls();
  }
  function render(value){
    view=value;
    $('game-admin-state').textContent=value.available?'Игровой мост на связи':value.message||'Игровой мост ещё не готов';
    $('game-admin-state').className='notice'+(value.available?'':' error');
    const meta=$('game-admin-meta');meta.replaceChildren();
    if(value.available)meta.append(node('span','Valheim '+(value.game||'—')+' · ValheimAdminRu '+(value.mod||'—')+' · '+(value.world||'—'),true),node('span',' · '+I18n.t('Обновлено: ')+fmtTime(value.at),true));
    options($('game-admin-executor'),value.players||[]);options($('game-admin-target'),value.players||[]);
    renderCatalog('item',value.items||[]);renderCatalog('mob',value.mobs||[]);
    table('game-admin-players',value.players||[],(row,player)=>{cell(row,player.name||'—',true);cell(row,player.steam_id,true);cell(row,roles[player.role]||'Игрок');cell(row,player.ready?'Совместимый мод':'Без совместимого мода');},4);
    table('game-admin-audit',value.audit||[],(row,entry)=>{
      const date=new Date(entry.utc);cell(row,Number.isNaN(date.getTime())?entry.utc:date.toLocaleString(I18n.locale),true);
      cell(row,entry.actor||'—',true);cell(row,actionNames[entry.action]||entry.action||'—',!Object.hasOwn(actionNames,entry.action));
      for(const key of ['details','result'])cell(row,(I18n.language==='en'?entry[key+'_en']||entry[key]:entry[key])||'—',true);
    },5);
    roleInfo();
  }
  function renderMessage(){
    const host=$('game-admin-result');host.hidden=!lastMessage;
    if(lastMessageEn)host.dataset.i18nSkip='';else delete host.dataset.i18nSkip;
    host.textContent=I18n.language==='en'&&lastMessageEn?lastMessageEn:lastMessage;host.className='notice'+(lastError?' error':'');
  }
  function message(value,error=false,valueEn=''){
    lastMessage=value;lastMessageEn=valueEn;lastError=error;renderMessage();
  }
  async function load(force=false){
    if(!csrf||loading||!force&&Date.now()-lastLoad<5000)return;
    const started=generation;loading=true;controls();
    try{const value=await api('/api/game-admin');if(started!==generation)return;lastLoad=Date.now();render(value);}
    catch(error){if(started===generation){view=null;$('game-admin-state').textContent=error.message;$('game-admin-state').className='notice error';}}
    finally{if(started===generation){loading=false;controls();}}
  }
  async function confirm(spec,data){
    const answer=confirmAction('Выполнить игровую команду? Перемещение и изменения мира могут повлиять на игроков и сохранение. Проверьте исполнителя, цель и параметры.');
    const details=node('span','',false,'game-admin-confirm-details');
    details.append(node('strong',spec.label),node('span','\n'+data.actor_steam+(data.target_steam?' → '+data.target_steam:'')+'\n'+Object.entries(data).filter(([key])=>!['session','action','actor_steam','target_steam'].includes(key)).map(([key,value])=>key+': '+value).join('\n'),true));
    $('confirm-text').append(details);return answer;
  }
  async function send(spec){
    if(reason(spec))return;
    for(const key of spec.inputKeys)if(!fields[key].reportValidity())return;
    let data={session:view.session,action:spec.action,actor_steam:actor().steam_id,...spec.values()};
    if(targetActions.has(spec.action))data.target_steam=target().steam_id;
    if(['SpawnItem','SpawnMob'].includes(spec.action)&&!(spec.action==='SpawnItem'?view.items:view.mobs).some(entry=>entry.prefab===data.prefab)){
      message('Выберите точный prefab из игрового каталога',true);return;
    }
    let approved=false;confirming=true;controls();
    try{approved=await confirm(spec,data);}finally{confirming=false;controls();}
    if(!approved)return;
    if(reason(spec))return;
    // A refreshed snapshot must not silently change the chosen world or actor.
    if(data.session!==view.session||data.actor_steam!==actor()?.steam_id||data.target_steam&&data.target_steam!==target()?.steam_id){message('Выбор игрока или игровая сессия изменились. Проверьте команду ещё раз.',true);return;}
    const started=generation;posting=true;controls();
    try{
      const result=await api('/api/game-admin',data);if(started!==generation)return;
      if(!/^[a-f0-9]{32}$/.test(result.id||''))throw new Error('Сервер вернул недопустимый ID игровой команды');
      pending={id:result.id,until:Date.now()+40000};message('Команда отправлена. Ожидаем подтверждение игрового клиента.');
      resultTimer=setTimeout(pollResult,500);
    }catch(error){if(started===generation)message(error instanceof TypeError||error instanceof SyntaxError?'Не удалось получить ответ. Результат неизвестен; проверьте игру перед повтором.':error.message,true);}
    finally{if(started===generation){posting=false;controls();}}
  }
  async function pollResult(){
    if(!pending||!csrf)return;
    const active=pending,started=generation;
    try{
      const result=await api('/api/game-admin/result?id='+encodeURIComponent(active.id));if(started!==generation||pending!==active)return;
      if(result.id!==active.id||!['pending','done','error'].includes(result.state))throw new Error('Недопустимый ответ на игровую команду');
      if(result.state!=='pending'){pending=null;message(result.message||'Игровая команда завершена',result.state==='error',result.message_en||'');controls();void load(true);return;}
    }catch(error){if(started!==generation||pending!==active)return;if(Date.now()>active.until){pending=null;message('Нет подтверждения клиента. Результат неизвестен; проверьте игру перед повтором.',true);controls();return;}}
    if(Date.now()>active.until){pending=null;message('Нет подтверждения клиента. Результат неизвестен; проверьте игру перед повтором.',true);controls();return;}
    resultTimer=setTimeout(pollResult,1000);
  }

  build();controls();
  $('game-admin-executor').addEventListener('change',roleInfo);$('game-admin-target').addEventListener('change',controls);
  $('game-admin-reload').onclick=()=>load(true);
  window.addEventListener('hearth-login',()=>{generation++;void load(true);});
  window.addEventListener('hearth-status',event=>{busy=Boolean(event.detail.busy);closing=Boolean(event.detail.closing);controls();if(location.hash==='#game-admin'||pending)void load();});
  window.addEventListener('hashchange',()=>{if(location.hash==='#game-admin')void load(true);});
  window.addEventListener('hearth-language',()=>{if(view)render(view);renderMessage();controls();});
  window.addEventListener('hearth-logout',()=>{
    generation++;clearTimeout(resultTimer);view=null;pending=null;posting=false;confirming=false;loading=false;busy=true;closing=false;lastLoad=0;
    $('game-admin-executor').replaceChildren();$('game-admin-target').replaceChildren();
    $('game-admin-state').textContent='Войдите в веб-панель';$('game-admin-meta').replaceChildren();$('game-admin-role').replaceChildren();
    $('game-admin-players').replaceChildren();$('game-admin-audit').replaceChildren();fields.point.replaceChildren();
    catalogSignatures.item=null;catalogSignatures.mob=null;renderCatalog('item',[]);renderCatalog('mob',[]);message('');controls();
  });
})();
