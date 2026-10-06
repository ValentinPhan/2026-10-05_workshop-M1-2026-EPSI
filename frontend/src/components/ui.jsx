import React, { useEffect, useState } from 'react';
import { Card, Slider, Statistic, Tag } from 'antd';

export function Panel({ title, extra, children }) {
  return (
    <Card
      title={title}
      extra={extra}
      style={{ height: '100%' }}
      styles={{ title: { fontSize: 13, letterSpacing: '0.08em', textTransform: 'uppercase' }, body: { display: 'flex', flexDirection: 'column', gap: 12 } }}
    >
      {children}
    </Card>
  );
}

const TAG_COLORS = { ok: 'success', warn: 'warning', danger: 'error', info: 'processing', neutral: 'default' };

export function StatusTag({ tone = 'neutral', children }) {
  return (
    <Tag color={TAG_COLORS[tone]} variant="outlined" style={{ marginInlineEnd: 0 }}>
      {children}
    </Tag>
  );
}

export function Stat({ title, value, suffix }) {
  return <Statistic title={title} value={value} suffix={suffix} styles={{ content: { fontSize: 22, fontVariantNumeric: 'tabular-nums' } }} />;
}

// Curseur synchronisé avec le serveur : suit `value` sauf pendant le glissement,
// et n'envoie la commande (`onCommit`) qu'au relâchement.
export function SyncedSlider({ value, onCommit, ...props }) {
  const [draft, setDraft] = useState(value);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (!dragging) setDraft(value);
  }, [value, dragging]);

  return (
    <Slider
      {...props}
      value={draft}
      onChange={(v) => { setDragging(true); setDraft(v); }}
      onChangeComplete={(v) => { setDragging(false); onCommit(v); }}
    />
  );
}

// Courbe SVG simple : `values` = tableau de nombres, `threshold` = ligne de seuil optionnelle.
export function LineChart({ values, min, max, threshold, color = 'var(--accent)', height = 90 }) {
  const W = 300;
  const H = 100;
  if (values.length < 2) return <div className="chart-empty" style={{ height }}>En attente de données…</div>;

  const lo = min ?? Math.min(...values);
  const hi = max ?? Math.max(...values);
  const span = hi - lo || 1;
  const x = (i) => (i / (values.length - 1)) * W;
  const y = (v) => H - ((Math.min(Math.max(v, lo), hi) - lo) / span) * H;
  const line = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');

  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ height }} role="img">
      <path d={`${line} L${W},${H} L0,${H} Z`} fill={color} opacity="0.12" />
      {threshold !== undefined && (
        <line x1="0" x2={W} y1={y(threshold)} y2={y(threshold)} className="chart-threshold" vectorEffect="non-scaling-stroke" />
      )}
      <path d={line} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
