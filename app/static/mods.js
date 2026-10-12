'use strict';
(() => {
  if (!$('mods')) return;
  const scopes={server:'Только сервер',client:'Только клиенты',both:'Сервер и клиенты'};
  const ZIP_LIMIT=128*1024*1024;
  let catalog=null,busy=true,closing=false,requesting=false,queued=false,fetching=false,fetchAgain=false,clientReady=false,generation=0,lastFetch=0;

  function controls(){
    const disabled=busy||closing||requesting||queued||!catalog?.available;
    document.querySelectorAll('[data-mod-action], #mods-install, #mods-upload').forEach(button=>button.disabled=disabled||button.dataset.modUnavailable==='true');
    $('mods-reload').disabled=closing||requesting||fetching;
    $('mods-mode-help').hidden=Boolean(catalog?.available);
    $('mods-busy').hidden=!(busy||requesting||queued);
    $('mods-client-link').hidden=!clientReady||busy||closing||requesting||queued;
  }
  function text(tag,value,literal=false,className=''){
    const node=document.createElement(tag);node.textContent=value;
    if(literal)node.dataset.i18nSkip='';if(className)node.className=className;return node;
  }
  function detail(list,label,value,literal=false){
    const group=document.createElement('div');group.append(text('dt',label),text('dd',value,literal));list.append(group);
  }
  function packageButton(label,action,pkg,unavailable=false){
    const button=text('button',label);button.type='button';button.dataset.modAction=action;
    button.dataset.modUnavailable=String(unavailable);
    if(unavailable)button.title='ZIP-пакет обновляется повторной загрузкой архива';
    button.onclick=()=>change(pkg.source==='builtin'&&action==='mod_update'?'mod_builtin':action,{id:pkg.id,...(action==='mod_toggle'?{enabled:!pkg.enabled}:{})},pkg.name||pkg.id);
    return button;
  }
  function render(value){
    catalog=value;
    let builtin=$('mods-builtin-admin');
    if(!builtin){builtin=document.createElement('article');builtin.id='mods-builtin-admin';builtin.className='card mods-client';$('mods-mode-help').after(builtin);}
    builtin.replaceChildren();builtin.hidden=!value.builtin_admin;
    if(value.builtin_admin){
      const info=value.builtin_admin,installed=value.packages?.find(p=>p.id===info.id);
      builtin.append(text('p','ВСТРОЕННЫЙ АДМИН-МОД',false,'eyebrow accent'),text('h3','Hearth Admin'),
        text('p','Игровое меню по F8: телепорты, помощь игрокам, предметы и мобы, рельеф, супермолот, строительство и журнал. Управляйте ими также из раздела «Игровые инструменты».',false,'muted'),
        text('p','Требуется на сервере и у всех игроков. Установщики на лендинге получат ту же версию. В игровом меню есть переключатель RU / EN.',false,'tiny'),
        text('p','Если ValheimAdminRu уже ставили вручную, сначала уберите прежнюю DLL с сервера и клиентов, чтобы избежать двух копий мода.',false,'tiny'),
        text('p','Целевые версии Valheim: '+info.games.join(', '),false,'tiny'));
      const version=document.createElement('p');version.append(text('span','Версия: '),text('span',info.version,true));builtin.append(version);
      const actions=document.createElement('div');actions.className='toolbar';
      const install=text('button',installed?'Переустановить встроенную версию':'Установить Hearth Admin');install.type='button';install.dataset.modAction='mod_builtin';install.onclick=()=>change('mod_builtin',{},'Hearth Admin '+info.version);actions.append(install);
      const link=text('a','Открыть игровые инструменты ↗');link.href='#game-admin';actions.append(link);builtin.append(actions);
    }
    let loader=$('mods-loader');
    if(!loader){loader=document.createElement('p');loader.id='mods-loader';loader.className='muted';$('mods-mode-help').after(loader);}
    loader.replaceChildren();loader.hidden=!value.loader?.version;
    if(value.loader?.version)loader.append(text('span','BepInEx · Версия: '),text('span',value.loader.version,true));
    $('mods-summary').textContent=value.packages?.length?'Установленных пакетов: '+value.packages.length:'Модов пока нет';
    const list=$('mods-packages');list.replaceChildren();
    if(!value.packages?.length){
      const empty=document.createElement('article');empty.className='card mods-empty';
      empty.append(text('h3','Соберите свой набор модов'),text('p','Добавьте пакет из Thunderstore или Hexium либо загрузите ZIP. Выбранные моды и их зависимости появятся здесь.'));list.append(empty);
    }
    for(const pkg of value.packages||[]){
      const card=document.createElement('article');card.className='card mods-package';
      const header=document.createElement('div');header.className='mods-package-heading';
      header.append(text('h3',pkg.name||pkg.id,true),text('span',pkg.enabled?'Включён':'Выключен',false,'mods-badge'+(pkg.enabled?'':' mods-badge-off')));card.append(header);
      card.append(text('p',pkg.id,true,'mods-package-id'));
      if(pkg.description)card.append(text('p',pkg.description,true,'muted mods-package-description'));
      const details=document.createElement('dl');details.className='mods-package-details';
      detail(details,'Версия',pkg.version||'—',true);
      detail(details,'Область установки',scopes[pkg.scope]||pkg.scope,!Object.hasOwn(scopes,pkg.scope));
      detail(details,'Источник',pkg.source==='builtin'?'Встроен в Hearth':pkg.source==='manual'?'ZIP вручную':pkg.source==='thunderstore'?'Thunderstore':pkg.source==='hexium'?'Hexium':pkg.source||'—',!['manual','thunderstore','hexium','builtin'].includes(pkg.source));
      const dependencies=(pkg.dependencies||[]).map(item=>typeof item==='string'?item:item.id||item.name||'—');
      detail(details,'Зависимости',dependencies.length?dependencies.join(', '):'Нет зависимостей',Boolean(dependencies.length));card.append(details);
      const actions=document.createElement('div');actions.className='toolbar mods-package-actions';
      actions.append(packageButton('Обновить','mod_update',pkg,pkg.source==='manual'),packageButton(pkg.enabled?'Выключить':'Включить','mod_toggle',pkg),packageButton('Удалить','mod_remove',pkg));card.append(actions);
      if(pkg.source_url){
        try{
          const source=new URL(pkg.source_url);
          if(source.protocol==='https:'&&['thunderstore.io','www.thunderstore.io','valheim.hexium.gg'].includes(source.hostname)){
            const link=text('a','Описание мода ↗');link.href=source.href;link.target='_blank';link.rel='noopener noreferrer';actions.append(link);
          }
        }catch{}
      }
      if(pkg.source==='manual')card.append(text('p','Чтобы обновить ZIP-пакет, загрузите новую версию архива.',false,'tiny'));
      list.append(card);
    }
    const client=$('mods-client-link');clientReady=false;client.hidden=true;client.removeAttribute('href');
    if(value.client_url){
      try{const url=new URL(value.client_url,location.href);if(['http:','https:'].includes(url.protocol)&&url.origin===location.origin){client.href=url.href;clientReady=true;}}catch{}
    }
    controls();
  }
  async function load(force=false){
    if(!csrf)return;
    if(fetching){if(force)fetchAgain=true;return;}
    if(!force&&Date.now()-lastFetch<10000)return;
    const started=generation;fetching=true;controls();
    try{
      const value=await api('/api/mods');
      if(started!==generation)return;
      lastFetch=Date.now();render(value);
    }catch(error){if(started===generation)$('mods-message').textContent=error.message;}
    finally{
      if(started===generation){fetching=false;controls();if(fetchAgain){fetchAgain=false;void load(true);}}
    }
  }
  async function confirmMod(message,identity,scope){
    const result=confirmAction(message);
    const details=document.createElement('span');details.className='mods-confirm-identity';details.dataset.i18nSkip='';details.textContent=identity;$('confirm-text').append(details);
    if(scope)$('confirm-text').append(document.createTextNode('\nОбласть установки: '+scopes[scope]));
    return result;
  }
  async function change(action,data,identity){
    if(busy||closing||requesting||queued||!catalog?.available)return;
    const prompts={
      mod_builtin:'Установить встроенный Hearth Admin на сервер и добавить его в набор для игроков? Перед применением — остановка игры и резервная копия. Если игра работала, она запустится снова.',
      mod_install:'Установить этот мод и зависимости? Перед применением панель остановит игру и создаст резервную копию. Затем вернёт прежнее состояние запуска. Совместимость модов проверьте отдельно.',
      mod_update:'Обновить этот мод? Перед применением панель остановит игру и создаст резервную копию. Если игра работала, она запустится снова.',
      mod_toggle:data.enabled?'Включить этот мод? Перед изменением — остановка игры и резервная копия. Моды для клиентов также должны быть установлены у игроков.':'Выключить этот мод? Перед изменением — остановка игры и резервная копия. Пакеты, которым он необходим, могут помешать отключению.',
      mod_remove:'Удалить этот мод? Перед изменением — остановка игры и резервная копия. Удаление может повлиять на мир и зависимые пакеты.'
    };
    const started=generation;requesting=true;controls();
    try{
      if(!await confirmMod(prompts[action],identity,data.scope))return;
      if(started!==generation||!csrf||busy||closing)return;
      await api('/api/action',{action,...data});
      if(started!==generation)return;
      queued=true;$('mods-message').textContent='Задача с модом принята. Ход выполнения — в обзоре и журнале.';
    }catch(error){if(started===generation)$('mods-message').textContent=error.message;}
    finally{if(started===generation){requesting=false;controls();if(queued)void refresh();}}
  }
  $('mods-source-form').onsubmit=event=>{
    event.preventDefault();const source=$('mods-source').value.trim();
    if(!source){$('mods-message').textContent='Укажите пакет Thunderstore / Hexium или ссылку на него';return;}
    void change('mod_install',{source,scope:$('mods-scope').value},source);
  };
  $('mods-upload-form').onsubmit=async event=>{
    event.preventDefault();if(busy||closing||requesting||queued||!catalog?.available)return;
    const file=$('mods-file').files[0],scope=$('mods-upload-scope').value;
    if(!file||!file.size||!file.name.toLowerCase().endsWith('.zip')){$('mods-message').textContent='Выберите непустой ZIP-архив мода';return;}
    if(file.size>ZIP_LIMIT){$('mods-message').textContent='ZIP-архив превышает 128 МиБ';return;}
    const started=generation;requesting=true;controls();
    try{
      if(!await confirmMod('Установить мод из этого ZIP? Перед применением панель остановит игру и создаст резервную копию. Загружайте архивы из доверенного источника.',file.name,scope))return;
      if(started!==generation||!csrf||busy||closing)return;
      const response=await fetch('/api/mods/upload?name='+encodeURIComponent(file.name)+'&scope='+encodeURIComponent(scope),{method:'POST',headers:{'Content-Type':'application/zip','X-Hearth':'1','X-CSRF-Token':csrf},body:file});
      if(response.status===401||response.status===403){showLogin();return;}
      let result;try{result=await response.json();}catch{throw new Error('Не удалось загрузить ZIP-архив. Проверьте ограничения прокси и повторите запрос.');}
      if(!response.ok)throw new Error(result.error||'Не удалось загрузить ZIP-архив');
      if(started!==generation)return;
      queued=true;$('mods-message').textContent='ZIP принят. Ход установки — в обзоре и журнале.';
    }catch(error){if(started===generation)$('mods-message').textContent=error.message;}
    finally{if(started===generation){requesting=false;controls();if(queued)void refresh();}}
  };
  $('mods-reload').onclick=()=>load(true);
  window.addEventListener('hearth-login',()=>load(true));
  window.addEventListener('hearth-status',event=>{
    const value=event.detail,wasBusy=busy;busy=Boolean(value.busy);closing=Boolean(value.closing);
    if(queued&&!busy&&!requesting&&['done','error'].includes(value.job?.state)){
      queued=false;$('mods-message').textContent=value.job.state==='error'?value.job.message:'Операция завершена. Проверьте обновлённый список модов.';void load(true);
    }else if(wasBusy&&!busy)void load(true);
    else if(!busy)void load();
    controls();
  });
  window.addEventListener('hearth-language',()=>{if(catalog)render(catalog);});
  window.addEventListener('hearth-logout',()=>{
    generation++;catalog=null;busy=true;closing=false;requesting=false;queued=false;fetching=false;fetchAgain=false;clientReady=false;lastFetch=0;
    $('mods-source-form').reset();$('mods-upload-form').reset();$('mods-packages').replaceChildren();$('mods-summary').textContent='';$('mods-message').textContent='';$('mods-client-link').hidden=true;$('mods-client-link').removeAttribute('href');controls();
    if($('mods-loader')){$('mods-loader').replaceChildren();$('mods-loader').hidden=true;}
  });
  controls();
})();
