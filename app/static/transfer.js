'use strict';
let importPreview=null, transferUploading=false, transferBusy=false, transferOperation=null;
function transferNotice(message,error=false){$('world-transfer-status').textContent=message;$('world-transfer-status').className=error?'notice error':'muted';}
function transferButtons(){for(const id of ['world-export','world-upload','world-inspect','world-import'])$(id).disabled=transferUploading||transferBusy;$('world-import').hidden=!importPreview;}
$('world-export').onclick=async()=>{
  if(!await confirmAction('Сохранить и экспортировать выбранный мир? Игра остановится на время упаковки, затем запустится, если работала. Конфиг V+ попадёт в архив; передавайте архив только владельцу принимающего сервера.'))return;
  try{transferOperation='export';await api('/api/action',{action:'export_world'});transferNotice('Готовим архив. Ход операции виден в обзоре; ссылка появится ниже.');await refresh();}catch(e){transferNotice(e.message,true);}
};
$('world-upload').onchange=()=>{importPreview=null;transferButtons();transferNotice('Выбранный архив ещё не проверен.');};
$('world-inspect').onclick=async()=>{
  const file=$('world-upload').files[0];
  if(!file||!file.size||file.size>1024**3){transferNotice('Выберите ZIP-архив размером до 1 ГиБ.',true);return;}
  importPreview=null;transferUploading=true;transferButtons();transferNotice('Загружаем и проверяем архив… Игра продолжает работать.');
  try{
    const response=await fetch('/api/world-import',{method:'POST',headers:{'Content-Type':'application/zip','X-Hearth':'1','X-CSRF-Token':csrf},body:file});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'Не удалось загрузить архив');
    importPreview=result;transferNotice(`Проверено: мир «${result.world}», Valheim ${result.game}, ${result.mode==='plus'?'V+ '+result.mod+' с конфигом':'без модов'}. Подтверждение действует 1 час. После импорта запустите сервер вручную.`);
  }catch(e){transferNotice(e.message,true);}finally{transferUploading=false;transferButtons();}
};
$('world-import').onclick=async()=>{
  const preview=importPreview;if(!preview)return;
  if(!await confirmAction(`Импортировать мир «${preview.world}»? Игроки будут отключены. Перед заменой создастся резервная копия. Одноимённое сохранение будет заменено; мир станет выбранным. ${preview.mode==='plus'?'Конфиг V+ на этом сервере также будет заменён. ':''}Сервер останется остановленным для проверки настроек.`))return;
  try{transferOperation='import';await api('/api/action',{action:'import_world',token:preview.token});importPreview=null;$('world-upload').value='';transferNotice('Импорт запущен. Дождитесь результата в обзоре, проверьте настройки и нажмите «Запустить».');await refresh();}catch(e){transferNotice(e.message,true);}finally{transferButtons();}
};
window.addEventListener('hearth-status',e=>{
  transferBusy=e.detail.busy;transferButtons();
  if(transferOperation&&!transferBusy){if(e.detail.job.state==='error')transferNotice(e.detail.job.message,true);else if(e.detail.job.state==='done')transferNotice(transferOperation==='export'?'Архив готов — скачайте его по ссылке ниже.':'Мир импортирован. Копия до переноса сохранена. Проверьте настройки и запустите сервер.');transferOperation=null;}$('world-exports').replaceChildren();
  for(const item of e.detail.exports||[]){const row=document.createElement('div');row.className='file-row';const link=document.createElement('a');link.href='/api/world-export/'+encodeURIComponent(item.name);link.textContent='Скачать '+item.name;row.append(link,document.createTextNode(' · '+bytes(item.bytes)));$('world-exports').append(row);}
});
window.addEventListener('hearth-logout',()=>{importPreview=null;$('world-upload').value='';$('world-exports').replaceChildren();transferNotice('');transferButtons();});
