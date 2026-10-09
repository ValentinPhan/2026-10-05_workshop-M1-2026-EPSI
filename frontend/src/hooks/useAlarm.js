import { useEffect, useState } from 'react';

// Sirène « bee-do » synthétisée (Web Audio : aucun fichier son). Se joue tant que `active` est vrai et que le son
// n'est pas coupé. Le navigateur n'autorise le son qu'après un clic de l'utilisateur : la connexion en tient lieu.
const CYCLE_MS = 900; // même durée que le clignotement des gyrophares (styles.css)
const KEY = 'sentinel.alarmSound';

function beep(ctx, freq, start, length) {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  const filter = ctx.createBiquadFilter();
  osc.type = 'sawtooth';
  osc.frequency.value = freq;
  filter.type = 'lowpass';
  filter.frequency.value = 1800;
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(0.09, start + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + length);
  osc.connect(filter).connect(gain).connect(ctx.destination);
  osc.start(start);
  osc.stop(start + length + 0.02);
}

export function useAlarm(active) {
  const [enabled, setEnabled] = useState(() => {
    try { return localStorage.getItem(KEY) !== 'off'; } catch { return true; }
  });

  // un contexte audio par alerte : fermé dès qu'elle cesse (pas de thread audio qui tourne pour rien)
  useEffect(() => {
    if (!active || !enabled) return undefined;
    const Ctx = window.AudioContext ?? window.webkitAudioContext;
    if (!Ctx) return undefined;
    const ctx = new Ctx();
    ctx.resume().catch(() => {});
    const cycle = () => {
      if (ctx.state !== 'running') return; // son bloqué par le navigateur : on reste silencieux
      const t = ctx.currentTime + 0.02;
      beep(ctx, 880, t, 0.26); // « bee »
      beep(ctx, 587, t + 0.3, 0.3); // « do »
    };
    cycle();
    const id = setInterval(cycle, CYCLE_MS);
    return () => {
      clearInterval(id);
      ctx.close();
    };
  }, [active, enabled]);

  const toggle = () => {
    setEnabled(!enabled);
    try { localStorage.setItem(KEY, enabled ? 'off' : 'on'); } catch { /* stockage indisponible : le choix vaut pour cette session */ }
  };
  return { enabled, toggle };
}
