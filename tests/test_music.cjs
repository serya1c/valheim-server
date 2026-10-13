const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function target() {
  const handlers = new Map();
  return {hidden:true, attributes:{},
    addEventListener(type, callback) {
      if (!handlers.has(type)) handlers.set(type, []);
      handlers.get(type).push(callback);
    },
    emit(type, event = {}) { for (const callback of handlers.get(type) || []) callback({type, ...event}); },
    setAttribute(name, value) { this.attributes[name] = value; },
  };
}
function fixture({saved = null, storageBlocked = false, mode = 'resolve'} = {}) {
  const audio = target(), toggle = target(), document = target(), window = target();
  audio.paused = true; audio.playCalls = 0; audio.pending = []; audio.mode = mode;
  audio.play = () => {
    ++audio.playCalls;
    if (audio.mode === 'blocked') return Promise.reject(Object.assign(new Error(), {name:'NotAllowedError'}));
    if (audio.mode === 'pending') return new Promise((resolve, reject) => audio.pending.push({
      resolve() { audio.paused = false; resolve(); }, reject,
    }));
    audio.paused = false;
    return Promise.resolve();
  };
  audio.pause = () => { audio.paused = true; };
  document.hidden = false;
  document.getElementById = id => ({'ambient-music-audio':audio, 'ambient-music-toggle':toggle})[id];
  let stored = saved, language = 'ru';
  const translations = {'Выключить звук':'Mute sound', 'Включить звук':'Enable sound'};
  window.I18n = {t:source => language === 'en' ? translations[source] || source : source};
  const context = {window, document, localStorage:{
    getItem() { if (storageBlocked) throw new Error('Storage denied'); return stored; },
    setItem(key, value) { if (storageBlocked) throw new Error('Storage denied'); stored = value; },
  }};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/static/music.js'), 'utf8'), context);
  return {audio, toggle, document, window, stored:()=>stored,
    language(value) { language = value; window.emit('hearth-language'); }};
}
const settle = async () => { await Promise.resolve(); await Promise.resolve(); };

(async () => {
  const f = fixture(); await settle();
  assert.equal(f.audio.paused, false, 'Background playback starts when browser policy permits it');
  assert.equal(f.audio.volume, 0.25);
  assert.equal(f.toggle.hidden, false);
  assert.equal(f.toggle.attributes['aria-label'], 'Выключить звук');
  f.toggle.emit('click');
  assert.equal(f.audio.paused, true); assert.equal(f.audio.muted, true);
  assert.equal(f.stored(), '1'); assert.equal(f.toggle.attributes['aria-pressed'], 'true');
  f.language('en'); assert.equal(f.toggle.attributes['aria-label'], 'Enable sound');
  f.toggle.emit('click'); await settle();
  assert.equal(f.audio.paused, false); assert.equal(f.stored(), '0');
  f.language('ru'); assert.equal(f.toggle.attributes['aria-label'], 'Выключить звук');

  const muted = fixture({saved:'1'}); await settle();
  assert.equal(muted.audio.playCalls, 0, 'Remembered mute avoids loading the track');
  muted.document.emit('pointerdown'); assert.equal(muted.audio.playCalls, 0);
  muted.toggle.emit('click'); await settle(); assert.equal(muted.audio.paused, false);

  const blocked = fixture({mode:'blocked', storageBlocked:true}); await settle();
  assert.equal(blocked.audio.paused, true);
  blocked.audio.mode = 'resolve';
  blocked.document.emit('pointerdown', {target:{closest:()=>({})}});
  assert.equal(blocked.audio.playCalls, 1, 'Mute-button interaction must not briefly start audio');
  blocked.document.emit('keydown', {key:'Shift'}); assert.equal(blocked.audio.playCalls, 1);
  blocked.document.emit('keydown', {key:'Enter'}); await settle();
  assert.equal(blocked.audio.paused, false, 'First eligible interaction retries blocked playback');
  blocked.document.emit('pointerdown'); assert.equal(blocked.audio.playCalls, 2);
  blocked.toggle.emit('click'); assert.equal(blocked.audio.paused, true);

  const touch = fixture({mode:'blocked'}); await settle();
  touch.document.emit('pointerdown'); await settle();
  touch.audio.mode = 'resolve'; touch.document.emit('click'); await settle();
  assert.equal(touch.audio.paused, false, 'Touch-generated click can retry after pointerdown was blocked');

  const late = fixture({mode:'pending'});
  late.toggle.emit('click'); late.audio.pending[0].resolve(); await settle();
  assert.equal(late.audio.paused, true, 'Late completion cannot undo mute');
  late.toggle.emit('click'); late.document.hidden = true; late.document.emit('visibilitychange');
  late.audio.pending[1].resolve(); await settle(); assert.equal(late.audio.paused, true);
  late.audio.mode = 'resolve'; late.document.hidden = false; late.document.emit('visibilitychange');
  await settle(); assert.equal(late.audio.paused, false);
  late.window.emit('pagehide'); assert.equal(late.audio.paused, true);
  late.window.emit('pageshow'); await settle(); assert.equal(late.audio.paused, false);
  late.audio.emit('error'); assert.equal(late.audio.paused, true);
  console.log('Background music, mute persistence, languages, gesture fallback and tab lifecycle checks passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
