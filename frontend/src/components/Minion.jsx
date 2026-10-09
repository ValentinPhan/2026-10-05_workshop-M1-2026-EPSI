import { memo, useEffect, useId, useRef } from 'react';

// Mascotte dessinée en SVG (aucune image externe). Les pupilles suivent le curseur, la figurine cligne des yeux
// et change d'humeur : `mood` = calme | vigilance | menace | offline (voir les règles .minion[data-mood] dans styles.css).
const EYES = [{ cx: 78, cy: 92 }, { cx: 122, cy: 92 }];
const MAX_LOOK = 7; // décalage maximal d'une pupille, en unités du viewBox

// memo : le dashboard se re-rend à chaque snapshot, la mascotte ne change que d'humeur.
function Minion({ mood = 'calme', shy = false, height = 96, className }) {
  const uid = useId().replace(/:/g, '');
  const svgRef = useRef(null);

  useEffect(() => {
    const svg = svgRef.current;
    const pupils = svg.querySelectorAll('.pupil');
    let raf = 0;
    let last = null;

    const look = () => {
      raf = 0;
      if (!last) return;
      const box = svg.getBoundingClientRect();
      const scale = box.width / 200; // px écran par unité du viewBox
      pupils.forEach((pupil, i) => {
        const ex = box.left + EYES[i].cx * scale;
        const ey = box.top + EYES[i].cy * scale;
        const dx = last.x - ex;
        const dy = last.y - ey;
        const dist = Math.hypot(dx, dy) || 1;
        const k = Math.min(MAX_LOOK, dist / (6 * scale)) / dist; // loin du curseur : plein regard ; tout près : regard doux
        pupil.style.transform = `translate(${dx * k}px, ${dy * k}px)`;
      });
    };
    const onMove = (e) => {
      last = { x: e.clientX, y: e.clientY };
      if (!raf) raf = requestAnimationFrame(look);
    };
    window.addEventListener('pointermove', onMove, { passive: true });
    return () => {
      window.removeEventListener('pointermove', onMove);
      cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <svg
      ref={svgRef}
      className={className ? `minion ${className}` : 'minion'}
      data-mood={mood}
      data-shy={shy}
      viewBox="0 0 200 270"
      height={height}
      width={(height * 200) / 270}
      role="img"
      aria-label={`Mascotte Sentinel-X : ${mood}`}
    >
      <defs>
        <linearGradient id={`${uid}-skin`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffe46b" />
          <stop offset="1" stopColor="#f4bd13" />
        </linearGradient>
        <linearGradient id={`${uid}-rim`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#d9dee6" />
          <stop offset="1" stopColor="#7d8794" />
        </linearGradient>
        <radialGradient id={`${uid}-glow`}>
          <stop offset="0" stopColor="#ff4b3e" stopOpacity="0.95" />
          <stop offset="1" stopColor="#ff4b3e" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`${uid}-dome`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ff7a6e" />
          <stop offset="1" stopColor="#c4180d" />
        </linearGradient>
        <clipPath id={`${uid}-body`}><rect x="40" y="22" width="120" height="216" rx="60" /></clipPath>
        {EYES.map((e, i) => <clipPath key={i} id={`${uid}-eye${i}`}><circle cx={e.cx} cy={e.cy} r="19" /></clipPath>)}
      </defs>

      <ellipse className="minion-shadow" cx="100" cy="258" rx="46" ry="6" />

      <g className="minion-body">
        <ellipse className="aura" cx="100" cy="130" rx="105" ry="150" fill={`url(#${uid}-glow)`} opacity="0.4" />

        {/* bras et mains (derrière le corps) */}
        <g className="minion-arm minion-arm-l"><ellipse cx="38" cy="182" rx="9" ry="22" fill={`url(#${uid}-skin)`} transform="rotate(14 38 182)" /><circle cx="31" cy="204" r="9" fill="#26262c" /></g>
        <g className="minion-arm minion-arm-r"><ellipse cx="162" cy="182" rx="9" ry="22" fill={`url(#${uid}-skin)`} transform="rotate(-14 162 182)" /><circle cx="169" cy="204" r="9" fill="#26262c" /></g>

        {/* gyrophares (en alerte seulement) : un de chaque côté de la tête, qui clignotent en alternance */}
        {[0, 1].map((side) => (
          // posés contre le crâne (plus bas que les yeux d'origine) : la plaque de fixation passe sous le corps
          <g key={side} className={`beacon beacon-${side}`} transform={side ? 'translate(200 16) scale(-1 1)' : 'translate(0 16)'}>
            <circle className="beacon-glow" cx="24" cy="52" r="36" fill={`url(#${uid}-glow)`} />
            <path className="beacon-rays" d="M12 52 L-12 40 M12 52 L-16 52 M12 52 L-12 64 M18 40 L4 24 M18 64 L4 80" />
            <rect x="38" y="36" width="18" height="32" rx="3" fill="#3a3a42" />
            <path className="beacon-dome" d="M48 38 H32 Q16 38 16 52 Q16 66 32 66 H48 Z" fill={`url(#${uid}-dome)`} />
            <path d="M33 43 Q23 44 21 52" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" opacity="0.55" />
          </g>
        ))}

        {/* chaussures */}
        <ellipse cx="80" cy="243" rx="22" ry="11" fill="#26262c" />
        <ellipse cx="120" cy="243" rx="22" ry="11" fill="#26262c" />

        {/* corps */}
        <rect x="40" y="22" width="120" height="216" rx="60" fill={`url(#${uid}-skin)`} />
        <g clipPath={`url(#${uid}-body)`}>
          {/* salopette */}
          <rect x="30" y="170" width="140" height="80" fill="#3d6fb0" />
          <rect x="74" y="146" width="52" height="40" rx="6" fill="#3d6fb0" />
          <rect x="86" y="160" width="28" height="18" rx="4" fill="#335d96" />
          <path d="M40 142 L76 160 M160 142 L124 160" stroke="#3d6fb0" strokeWidth="11" strokeLinecap="round" />
          <circle cx="76" cy="160" r="4.5" fill="#ffd83b" />
          <circle cx="124" cy="160" r="4.5" fill="#ffd83b" />
          {/* sangle des lunettes */}
          <rect x="30" y="84" width="140" height="16" fill="#26262c" />
          {/* lumière */}
          <rect x="52" y="30" width="16" height="120" rx="8" fill="#fff" opacity="0.18" />
        </g>

        {/* cheveux */}
        <g className="hair" stroke="#26262c" strokeWidth="2.4" strokeLinecap="round" fill="none">
          <path d="M100 24 C96 12 88 8 82 8" /><path d="M100 24 C100 10 100 4 100 2" /><path d="M100 24 C106 12 114 8 120 9" />
          <path d="M96 25 C86 18 78 18 72 22" /><path d="M104 25 C114 18 122 18 128 23" />
        </g>

        {/* gyrophare du dessus : remplace les cheveux en alerte (clignote deux fois plus vite que ceux des côtés) */}
        <g className="beacon beacon-top">
          <circle className="beacon-glow" cx="100" cy="4" r="48" fill={`url(#${uid}-glow)`} />
          <path className="beacon-rays" d="M70 -2 L52 -14 M130 -2 L148 -14 M100 -18 L100 -40 M80 -14 L70 -32 M120 -14 L130 -32" />
          <rect x="82" y="14" width="36" height="12" rx="3" fill="#3a3a42" />
          <path className="beacon-dome" d="M86 16 Q86 -10 100 -10 Q114 -10 114 16 Z" fill={`url(#${uid}-dome)`} />
          <path d="M91 10 Q91 -2 99 -4" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" opacity="0.55" />
        </g>

        {/* lunettes */}
        {EYES.map((e, i) => (
          <g key={i}>
            <circle cx={e.cx} cy={e.cy} r="25" fill={`url(#${uid}-rim)`} />
            <circle cx={e.cx} cy={e.cy} r="19" fill="#fff" />
            <g clipPath={`url(#${uid}-eye${i})`}>
              <g className="pupil">
                <g className="pupil-core">
                  <circle cx={e.cx} cy={e.cy} r="9.5" className="iris" />
                  <circle cx={e.cx} cy={e.cy} r="4.6" fill="#17110a" />
                  <circle cx={e.cx - 3.2} cy={e.cy - 3.4} r="2.2" fill="#fff" />
                </g>
              </g>
              <rect className="lid" x={e.cx - 20} y={e.cy - 20} width="40" height="40" fill="#e9b811" />
            </g>
            <path d={`M${e.cx - 14} ${e.cy - 14} A20 20 0 0 1 ${e.cx + 4} ${e.cy - 20}`} className="glint" />
          </g>
        ))}

        {/* sourcils */}
        <g className="brows" stroke="#26262c" strokeWidth="4.5" strokeLinecap="round">
          <path className="brow-l" d="M56 60 L94 66" />
          <path className="brow-r" d="M144 60 L106 66" />
        </g>

        {/* bouche */}
        <path className="mouth mouth-calme" d="M82 131 Q100 148 118 131" />
        <path className="mouth mouth-vigilance" d="M85 138 Q92 132 100 137 T115 136" />
        <g className="mouth-menace">
          <path d="M82 128 Q100 116 118 128 Q100 160 82 128 Z" fill="#4b1d18" />
          <path d="M86 128.5 Q100 120 114 128.5 L112 133 Q100 128 88 133 Z" fill="#fff" />
        </g>
        <path className="mouth mouth-offline" d="M92 136 Q100 140 108 136" />

        <text className="zzz" x="150" y="40">z</text>
        <text className="zzz zzz-2" x="164" y="22">Z</text>
      </g>
    </svg>
  );
}

export default memo(Minion);
