const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const context={window:{addEventListener(){},dispatchEvent(){}},document:{addEventListener(){},documentElement:{},querySelectorAll:()=>[],createTreeWalker:()=>({nextNode:()=>false})},localStorage:{getItem:()=> 'en',setItem(){}},navigator:{language:'en-GB'},NodeFilter:{SHOW_TEXT:4},CustomEvent:class{}};
vm.createContext(context);
for(const file of ['i18n-catalog.js','i18n.js','mod-ru.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static',file),'utf8'),context);
const t=context.window.I18n;
const fixture=fs.readFileSync(path.join(__dirname,'fixtures/valheim-plus-10.4.cfg'),'utf8');
let section='';const entries=[];
for(const line of fixture.split(/\r?\n/)){
  if(line.startsWith('['))section=line.slice(1,-1);
  else if(/^[A-Za-z]+ = /.test(line)){const [key,value]=line.split(' = ');entries.push({id:section+'/'+key,section,key,value,options:[],description:'Original author description'});}
}
assert.equal(entries.length,28);
for(const entry of entries){
  const label=context.modLabel(entry.key);
  assert(!label.startsWith('Дополнительный параметр:'),entry.id+' needs a Russian label');
  assert(!/[А-Яа-яЁё]/.test(t.t(label)),entry.id+' needs an English label');
  assert(!context.modDescription(entry).startsWith('Для этого параметра пока нет'),entry.id+' needs Russian help');
  assert(!/[А-Яа-яЁё]/.test(context.modDescriptionEn(entry)),entry.id+' needs English help');
}
assert.equal(t.t('Адреналин'),'Adrenaline');
for(const [value,english] of [['false','No'],['true','Yes']]){
  const limits=context.modConstraints({kind:'bool',options:[],default:value});
  assert.equal(t.t(limits),'Values: Yes (true) / No (false). Default: '+english+'.');
}

assert.equal(t.t(context.modLabel('drakkarInventoryRows')),'Drakkar — rows');
assert.equal(t.t(context.modLabel('longboatInventoryRows')),'Longship — rows');
const find=id=>entries.find(e=>e.id===id);
assert.match(context.modDescription(find('Map/syncPins')),/Удаление.*у всех/);
assert.match(context.modDescriptionEn(find('Map/syncPins')),/offline players/);
assert.match(context.modDescriptionEn(find('Pickable/seeds')),/not carried over automatically/);
assert.match(context.modDescriptionEn(find('Adrenaline/trinketCostMultiplier')),/below −99 are treated as −99/);
assert.match(context.modDescriptionEn(find('Windmill/stopAutoFuelOatThreshold')),/Barley and oat seeds/);
assert.match(context.modDescriptionEn(find('LootDrop/callerMouldDropChanceMultiplier')),/Stacks with lootDropChanceMultiplier/);
const flags={kind:'text',flags:true,options:['None','Boar','Wolf','Moose','All'],default:'All'};
assert.match(context.modConstraints(flags),/через запятую/);
assert.match(t.t(context.modConstraints(flags)),/^Flags: one or more comma-separated values/);
const mixed={...find('Tameable/animalTypes'),options:flags.options};
assert.match(context.modDescription(mixed),/moose — лось/);
assert.equal(t.t('Каталог BepInEx не должен быть ссылкой'),'The BepInEx directory must not be a symbolic link');
assert.equal(t.t('Конфликт данных V+: Карта-123.json. Старые файлы сохранены; сравните их перед переносом'),'V+ data conflict: Карта-123.json. The old files were preserved; compare them before migration');
t.setLanguage('ru');assert.equal(t.t('Адреналин'),'Адреналин');
console.log('V+ 10.4 fields, RU/EN labels, semantic help, and animal flags passed');
