'use strict';
(() => {
  const audio = document.getElementById('ambient-music-audio');
  const toggle = document.getElementById('ambient-music-toggle');
  if (!audio || !toggle) return;

  const storageKey = 'hearth-ambient-muted';
  let muted = false, awaitingGesture = false, generation = 0;
  try { muted = localStorage.getItem(storageKey) === '1'; } catch {}
  audio.volume = 0.25;
  audio.muted = muted;

  function render() {
    const source = muted ? 'Включить звук' : 'Выключить звук';
    const caption = window.I18n ? window.I18n.t(source) : source;
    toggle.setAttribute('aria-label', caption);
    toggle.setAttribute('title', caption);
    toggle.setAttribute('aria-pressed', String(muted));
  }

  function stop() {
    ++generation;
    awaitingGesture = false;
    audio.pause();
  }

  async function play() {
    if (muted || document.hidden) return;
    const attempt = ++generation;
    awaitingGesture = false;
    try {
      await audio.play();
      if (attempt !== generation) {
        if (muted || document.hidden) audio.pause();
        return;
      }
      if (muted || document.hidden) audio.pause();
    } catch (error) {
      if (attempt !== generation) return;
      // Browser policy can require a real user gesture before audible playback.
      awaitingGesture = error?.name === 'NotAllowedError';
    }
  }

  toggle.addEventListener('click', () => {
    muted = !muted;
    audio.muted = muted;
    try { localStorage.setItem(storageKey, muted ? '1' : '0'); } catch {}
    render();
    if (muted) stop();
    else play();
  });
  function wake(event) {
    if (event.target?.closest?.('#ambient-music-toggle')) return;
    if (event.type === 'keydown' && ['Alt', 'Control', 'Meta', 'Shift', 'Escape'].includes(event.key)) return;
    if (awaitingGesture && !muted && !document.hidden) play();
  }
  document.addEventListener('pointerdown', wake, {passive: true});
  document.addEventListener('click', wake);
  document.addEventListener('keydown', wake);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stop();
    else play();
  });
  audio.addEventListener('error', stop);
  window.addEventListener('pagehide', stop);
  window.addEventListener('pageshow', () => {
    if (!muted && !document.hidden && audio.paused) play();
  });
  window.addEventListener('hearth-language', render);
  toggle.hidden = false;
  render();
  play();
})();
