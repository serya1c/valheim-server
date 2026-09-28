/* Russian source strings are stable message keys. Only presentation is translated. */
'use strict';
(() => {
  const catalog=window.HEARTH_EN;
  const storageKey='hearth-language';
  let language='ru';
  try { const saved=localStorage.getItem(storageKey);language=saved==='en'?'en':saved==='ru'?'ru':navigator.language.toLowerCase().startsWith('ru')?'ru':'en'; } catch {}
  const records=new WeakMap();
  const escape=s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const phrases=Object.keys(catalog).filter(s=>s.trim()).sort((a,b)=>b.length-a.length);
  const fragments=new RegExp(phrases.map(s=>'(?<![А-Яа-яЁё])'+escape(s)+'(?![А-Яа-яЁё])').join('|'),'gu');
  const patterns=(window.HEARTH_PATTERNS||[]).map(([ru,en,translated=[]])=>({expression:new RegExp('^'+ru.split(/(\{\d+\})/).map(s=>/^\{\d+\}$/.test(s)?'(.*?)':escape(s)).join('')+'$','s'),en,translated}));
  function translate(source){
    if(language==='ru'||typeof source!=='string')return source;
    if(Object.hasOwn(catalog,source))return catalog[source];
    const core=source.trim();
    if(Object.hasOwn(catalog,core))return source.replace(core,catalog[core]);
    for(const p of patterns){const match=core.match(p.expression);if(match)return source.replace(core,p.en.replace(/\{(\d+)\}/g,(_,n)=>p.translated.includes(Number(n))?translate(match[Number(n)+1]):match[Number(n)+1]));}
    return source.replace(fragments,match=>catalog[match]);
  }
  const skip='script,style,textarea,pre,code,[data-i18n-skip]';
  function renderValue(node,key,current,write,explicit){
    let record=records.get(node);if(!record){record={};records.set(node,record);}
    let state=record[key];
    if(!state||current!==state.output)state=record[key]={source:current,output:current};
    const output=language==='en'&&explicit!==undefined?explicit:translate(state.source);
    if(current!==output)write(output);
    state.output=output;
  }
  let observer;
  function apply(){
    observer?.disconnect();
    document.documentElement.lang=language;
    const walker=document.createTreeWalker(document.documentElement,NodeFilter.SHOW_TEXT);
    while(walker.nextNode()){
      const node=walker.currentNode, parent=node.parentElement;
      if(!parent||parent.closest(skip)||!node.nodeValue.trim())continue;
      renderValue(node,'text',node.nodeValue,value=>node.nodeValue=value,parent.dataset.i18nEn);
    }
    for(const node of document.querySelectorAll('[title],[placeholder],[aria-label]')){
      if(node.closest('[data-i18n-skip]'))continue;
      for(const key of ['title','placeholder','aria-label'])if(node.hasAttribute(key))renderValue(node,key,node.getAttribute(key),value=>node.setAttribute(key,value));
    }
    for(const button of document.querySelectorAll('[data-language]'))button.setAttribute('aria-pressed',String(button.dataset.language===language));
    observer?.observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['title','placeholder','aria-label','data-i18n-en']});
  }
  function setLanguage(value,persist=true){
    if(!['ru','en'].includes(value))return;
    language=value;
    if(persist)try{localStorage.setItem(storageKey,value);}catch{}
    // Existing controls are never recreated: drafts, file selections, and dialogs survive.
    window.dispatchEvent(new CustomEvent('hearth-language',{detail:value}));
    apply();
  }
  window.I18n={t:translate,apply,setLanguage,get language(){return language;},get locale(){return language==='ru'?'ru-RU':'en-GB';}};
  document.addEventListener('DOMContentLoaded',()=>{
    for(const host of document.querySelectorAll('[data-language-switch]')){
      host.setAttribute('role','group');host.setAttribute('aria-label','Язык / Language');
      for(const lang of ['ru','en']){const button=document.createElement('button');button.type='button';button.textContent=lang.toUpperCase();button.dataset.language=lang;button.onclick=()=>setLanguage(lang);host.append(button);}
    }
    observer=new MutationObserver(apply);apply();
  });
  window.addEventListener('storage',e=>{if(e.key===storageKey&&['ru','en'].includes(e.newValue))setLanguage(e.newValue,false);});
})();
