'use strict';
let configData = null, configTab = 'server', configDirty = false, configSaving = false, configBusy = false, configLoadedWorld = '';
function optionList(select, values, selected) {
  select.replaceChildren();
  Object.entries(values).forEach(([value,label])=>{const o=document.createElement('option');o.value=value;o.textContent=label;select.append(o);});
  select.value=selected;
}
function configNotice(text, error=false){$('config-status').textContent=text;$('config-status').className=error?'notice error':'muted';}
function configButtons(){document.querySelectorAll('#config-form input,#config-form select,#config-form textarea,[data-tab],#config-reload').forEach(e=>e.disabled=configSaving);$('cfg-public').disabled=configSaving||Boolean(configData?.listing_required);for(const id of ['config-save','config-apply'])$(id).disabled=!configData||configSaving||configBusy||(configTab==='mod'&&!configData.mod.available);}
function switchConfigTab(name){configTab=name;$('config-apply').hidden=['landing','panel'].includes(name);$('config-save').textContent=name==='panel'?'Сохранить настройки':name==='landing'?'Опубликовать изменения':'Сохранить без запуска';document.querySelectorAll('[data-tab]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.tab===name)));for(const t of ['server','world','mod','landing','panel'])$('config-'+t).hidden=t!==name;configButtons();}
function loadWorldRules(name){
  const defaults={managed:false,preset:'normal',modifiers:Object.fromEntries(Object.keys(configData.modifiers).map(k=>[k,''])),keys:[]};
  const w=configData.worlds[name]||defaults;configLoadedWorld=name;
  $('cfg-world-managed').checked=w.managed;optionList($('cfg-preset'),configData.presets,w.preset);
  $('world-modifiers').replaceChildren();
  Object.entries(configData.modifiers).forEach(([key,[label,values]])=>{const l=document.createElement('label');l.textContent=label;const s=document.createElement('select');s.dataset.modifier=key;s.setAttribute('aria-label',label);optionList(s,values,w.modifiers[key]||'');l.append(s);$('world-modifiers').append(l);});
  $('world-keys').replaceChildren();
  Object.entries(configData.world_keys).forEach(([key,label])=>{const l=document.createElement('label');l.className='check-label';const c=document.createElement('input');c.type='checkbox';c.dataset.worldKey=key;c.checked=w.keys.includes(key);l.append(c,document.createTextNode(label));$('world-keys').append(l);});
  $('world-rules').disabled=!w.managed;
}
function renderMod(){
  $('mod-fields').replaceChildren();const mod=configData.mod;
  $('mod-info').textContent=configData.server.mode==='vanilla'?'Выбран ванильный режим. Конфигурация V+ сохранена для возврата, но в ванильном релизе не используется.':mod.available?`${mod.filename} · Параметров: ${mod.entries.length}. Технические имена оставлены рядом с переводом.`:'Файл мода пока не создан. Запустите установленный V+ один раз и нажмите «Перечитать».';
  const groups=new Map();
  mod.entries.forEach(e=>{
    if(!groups.has(e.section)){const d=document.createElement('details');d.className='mod-section';const s=document.createElement('summary');s.textContent=MOD_SECTIONS_RU[e.section]||`Раздел ${e.section}`;d.append(s);const grid=document.createElement('div');grid.className='settings-grid';d.append(grid);groups.set(e.section,{d,grid});$('mod-fields').append(d);}
    const label=document.createElement('div');label.className='mod-field';const title=modLabel(e.key);const heading=document.createElement('span');heading.textContent=title;label.append(heading);
    const technical=document.createElement('small');technical.textContent=e.section+'.'+e.key;label.append(technical);
    let control;
    if(e.kind==='bool'||e.options.length){control=document.createElement('select');optionList(control,e.kind==='bool'?{'false':'Нет','true':'Да'}:Object.fromEntries(e.options.map(v=>[v,modOption(v)])),e.value);}
    else{control=document.createElement('input');control.type=e.kind==='int'||e.kind==='float'?'number':'text';control.value=e.value;control.maxLength=2048;if(control.type==='number'){control.step=e.kind==='int'?'1':'any';if(e.min!==null)control.min=e.min;if(e.max!==null)control.max=e.max;}}
    control.setAttribute('aria-label',title+' ('+e.id+')');control.dataset.cfgId=e.id;control.dataset.kind=e.kind;label.append(control);
    const description=modDescription(e), help=document.createElement('small');help.className='field-help';help.id='mod-help-'+e.id.replace(/[^a-zA-Z0-9_-]/g,'-');help.textContent=description;help.dataset.i18nEn=e.description||'No description provided by the mod author. See the setting name and value limits below.';label.append(help);
    const limits=document.createElement('small');limits.className='field-limits';limits.id=help.id+'-limits';limits.textContent=modConstraints(e);label.append(limits);control.setAttribute('aria-describedby',help.id+' '+limits.id);
    if(e.description){const source=document.createElement('details');source.className='mod-source';const summary=document.createElement('summary');summary.textContent='Комментарий автора (оригинал)';const text=document.createElement('p');text.dataset.i18nSkip='';text.textContent=e.description;source.append(summary,text);label.append(source);}
    label.dataset.search=(title+' '+description+' '+(e.description||'')+' '+I18n.t(title)+' '+e.id+' '+(MOD_SECTIONS_RU[e.section]||'')).toLowerCase();groups.get(e.section).grid.append(label);
  });
}
async function loadConfig(force=false){
  if(configSaving)return;
  if(configDirty&&!force&&!await confirmAction('Перечитать настройки и отменить несохранённые изменения во всех вкладках?'))return;
  try{
    configData=await api('/api/config');configDirty=false;
    for(const key of ['backup_hours','backup_keep'])$('panel-'+key).value=configData.panel[key];$('panel-cookie_secure').checked=configData.panel.cookie_secure;$('panel-password').value='';$('panel-current_password').value='';
    for(const key of ['title','description','description_en','address','community_url','site_url'])$('landing-'+key).value=configData.landing[key];
    for(const key of ['name','saveinterval','backups','backupshort','backuplong'])$('cfg-'+key).value=configData.server[key];
    $('cfg-mode').value=configData.server.mode;$('cfg-add_site').checked=configData.server.add_site;
    $('ports-info').textContent=`UDP: ${configData.ports.game}–${configData.ports.query}. Публикация портов задаётся в Compose, применяется пересозданием контейнера. Другой копии нужны отдельные порты, имя проекта Compose и том данных.`;
    $('cfg-password').value='';$('cfg-public').checked=configData.server.public;$('listing-info').textContent=(configData.listing_required?'Публикация в Steam включена принудительно. ':'')+'Имя в списке: '+configData.advertised_name+'. Доступность извне зависит от указанных ниже UDP-портов и работы Steam.';$('cfg-world-name').value=configData.world_name;
    $('known-worlds').replaceChildren();configData.world_names.forEach(name=>{const o=document.createElement('option');o.value=name;$('known-worlds').append(o);});
    loadWorldRules(configData.world_name);renderMod();$('mod-search').value='';
    configNotice('Загружены сохранённые настройки. Изменения в каждой вкладке сохраняются отдельно.');configButtons();
  }catch(e){configNotice(e.message,true);}
}
function currentConfigValues(){
  if(configTab==='panel')return {backup_hours:Number($('panel-backup_hours').value),backup_keep:Number($('panel-backup_keep').value),cookie_secure:$('panel-cookie_secure').checked,password:$('panel-password').value,current_password:$('panel-current_password').value};
  if(configTab==='landing')return Object.fromEntries(['title','description','description_en','address','community_url','site_url'].map(k=>[k,$('landing-'+k).value]));
  if(configTab==='server')return {mode:$('cfg-mode').value,add_site:$('cfg-add_site').checked,name:$('cfg-name').value,password:$('cfg-password').value,public:$('cfg-public').checked,...Object.fromEntries(['saveinterval','backups','backupshort','backuplong'].map(k=>[k,Number($('cfg-'+k).value)]))};
  if(configTab==='world')return {name:$('cfg-world-name').value.trim(),rules:{managed:$('cfg-world-managed').checked,preset:$('cfg-preset').value,modifiers:Object.fromEntries([...document.querySelectorAll('[data-modifier]')].map(e=>[e.dataset.modifier,e.value])),keys:[...document.querySelectorAll('[data-world-key]:checked')].map(e=>e.dataset.worldKey)}};
  return Object.fromEntries([...document.querySelectorAll('[data-cfg-id]')].map(e=>[e.dataset.cfgId,e.value]).filter(([id,value])=>configData.mod.entries.find(e=>e.id===id).value!==value));
}
async function saveConfig(restart){
  if(!configData||configSaving)return;
  const panel=$('config-'+configTab);for(const input of panel.querySelectorAll('input,select,textarea')){if(!input.disabled&&!input.reportValidity())return;}
  if(configTab==='world'&&$('cfg-world-name').value.trim()!==configLoadedWorld){configNotice('Подтвердите выбор имени мира: выйдите из поля, затем проверьте его правила.',true);return;}
  const scope=configTab, names={server:'сервера',world:'мира',mod:'Valheim Plus',landing:'лендинга',panel:'панели'};
  if(!await confirmAction(['landing','panel'].includes(scope)?'Сохранить этот раздел? Другие вкладки не сохранятся. Игра продолжит работать. При смене пароля панели потребуется заново войти.':`Сохранить настройки ${names[scope]}? Сервер остановится, игроки будут отключены. Перед изменением будет создана копия. ${restart?'После сохранения установленный сервер запустится. Смена режима применяется отдельно через «Обновления».':'Сервер останется остановленным.'} Изменения остальных вкладок не сохраняются и будут перечитаны.`))return;
  try{
    configSaving=true;configButtons();
    await api('/api/action',{action:'configure',scope,revision:configData.revision,panel_revision:configData.panel_revision,values:currentConfigValues(),restart});
    configNotice('Сохранение… Дождитесь результата.');
    let s;
    do{await new Promise(r=>setTimeout(r,1000));s=await api('/api/status');}while(s.busy);
    if(s.job.state==='error')throw new Error(s.job.message);
    configSaving=false;await loadConfig(true);configNotice(['landing','panel'].includes(scope)?'Настройки обновлены. Игра продолжает работать.':restart?'Настройки сохранены. Проверьте состояние запуска в обзоре.':'Настройки сохранены. Сервер оставлен остановленным.');await refresh();
  }catch(e){configNotice(e.message,true);}
  finally{configSaving=false;configButtons();}
}
$('config-form').onsubmit=e=>e.preventDefault();
$('config-form').addEventListener('input',e=>{if(e.target.id!=='mod-search'){configDirty=true;configNotice('Есть несохранённые изменения.');}});
$('config-reload').onclick=()=>loadConfig();
$('settings-nav').addEventListener('click',()=>{if(!configData)loadConfig();});
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{switchConfigTab(b.dataset.tab);if(!configData)loadConfig();});
$('cfg-world-managed').onchange=()=>{$('world-rules').disabled=!$('cfg-world-managed').checked;};
$('cfg-world-name').onchange=()=>{if(configData){loadWorldRules($('cfg-world-name').value.trim());configNotice('Загружены правила выбранного имени мира. Проверьте их перед сохранением.');}};
$('mod-search').oninput=()=>{const q=$('mod-search').value.toLowerCase().trim();document.querySelectorAll('.mod-section').forEach(section=>{let count=0;section.querySelectorAll('.mod-field').forEach(row=>{row.hidden=!(row.dataset.search+' '+row.textContent.toLowerCase()).includes(q);if(!row.hidden)count++;});section.hidden=count===0;if(q)section.open=true;});};
$('config-save').onclick=()=>saveConfig(false);$('config-apply').onclick=()=>saveConfig(true);
window.addEventListener('beforeunload',e=>{if(configDirty){e.preventDefault();e.returnValue='';}});
window.addEventListener('hearth-status',e=>{configBusy=e.detail.busy;configButtons();});
window.addEventListener('hearth-login',()=>{configData=null;configDirty=false;loadConfig(true);});
window.addEventListener('hearth-logout',()=>{configData=null;configDirty=false;$('cfg-password').value='';$('panel-password').value='';$('panel-current_password').value='';configButtons();});
if(csrf)loadConfig(true);
