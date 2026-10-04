'use strict';
(() => {
  let health=null;
  const unavailable='Недоступно';
  function amount(value){return value===null||value===undefined?unavailable:bytes(value);}
  function render(value){
    health=value;
    if(!value){$('health-sampled').textContent='Сведения о состоянии пока недоступны';return;}
    $('health-process').textContent=value.process.running?'Процесс работает':'Процесс остановлен';
    $('health-a2s').textContent=value.a2s.fresh?'Есть свежий ответ A2S':value.a2s.last_response_at?'Последний ответ: '+fmtTime(value.a2s.last_response_at):'Ответ A2S ещё не получен';
    $('health-a2s-age').textContent=value.a2s.age_seconds===null?'':Math.floor(value.a2s.age_seconds)+' с назад';
    $('health-cpu').textContent=value.process.cpu_percent===null?unavailable:value.process.cpu_percent.toFixed(1)+'%';
    $('health-game-memory').textContent=amount(value.process.rss_bytes);
    $('health-container-memory').textContent=amount(value.container.memory_bytes);
    $('health-container-limit').textContent=value.container.memory_limit_bytes===null?'Лимит cgroup не определён':'Лимит: '+amount(value.container.memory_limit_bytes);
    $('health-disk').textContent=amount(value.disk.free_bytes);
    $('health-disk-total').textContent=value.disk.total_bytes===null?'':'Всего: '+amount(value.disk.total_bytes);
    $('health-save').textContent=value.world.last_save_at===null?'Запись мира пока не найдена':fmtTime(value.world.last_save_at);
    $('health-world').textContent=value.world.name||'—';
    $('health-backup').textContent=value.backup.last_success_at===null?'Завершённых копий пока нет':fmtTime(value.backup.last_success_at);
    $('health-sampled').textContent=value.sampled_at===null?'Ожидаем измерения':'Измерено: '+fmtTime(value.sampled_at);
    const diagnostics=$('health-diagnostics');diagnostics.replaceChildren();
    if(!value.diagnostics.length){diagnostics.textContent='По доступным измерениям проблем не обнаружено. Вход игроков проверяйте отдельно.';return;}
    value.diagnostics.forEach(item=>{
      const notice=document.createElement('article');notice.className='notice'+(item.level==='warning'?' error':'');
      const title=document.createElement('strong');title.textContent=item.title;
      const detail=document.createElement('p');detail.textContent=item.detail;
      const action=document.createElement('a');action.textContent=item.action;action.href=item.link;
      notice.append(title,detail,action);diagnostics.append(notice);
    });
  }
  window.addEventListener('hearth-status',event=>render(event.detail.health));
  window.addEventListener('hearth-language',()=>{if(health)render(health);});
  window.addEventListener('hearth-logout',()=>{
    health=null;
    for(const id of ['health-process','health-a2s','health-a2s-age','health-cpu','health-game-memory','health-container-memory','health-container-limit','health-disk','health-disk-total','health-save','health-world','health-backup','health-sampled','health-diagnostics'])$(id).textContent='';
  });
})();
