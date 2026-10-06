// Dessine sur le canvas : l'image de la caméra, puis les résultats de YOLO reçus avec CETTE image
// (carrés rouges, silhouettes, menace). Positions normalisées 0..1, donc indépendantes de la taille de l'image.
const RED = '#ff3b30';
const THREAT_COLORS = { Calme: '#3ecf8e', Vigilance: '#f5a524', Menace: '#ff3b30' };

// Vue « miroir » comme un selfie : gauche et droite inversés par rapport à la caméra. Seule l'image et les
// positions sont retournées, les textes restent lisibles. Mettre false pour la caméra du Pi (vue non miroir).
const MIRROR = true;
const fx = (x) => (MIRROR ? 1 - x : x);

function drawBox(ctx, d, w, h, lineWidth, fontSize) {
  const { x, y, w: bw, h: bh } = d.bbox;
  const px = (MIRROR ? 1 - x - bw : x) * w;
  const py = y * h;

  if (d.polygon?.length) {
    // silhouette (modèle de segmentation) : remplissage translucide + contour
    ctx.beginPath();
    d.polygon.forEach(([sx, sy], i) => (i ? ctx.lineTo(fx(sx) * w, sy * h) : ctx.moveTo(fx(sx) * w, sy * h)));
    ctx.closePath();
    ctx.fillStyle = 'rgba(255, 59, 48, 0.30)';
    ctx.fill();
    ctx.strokeStyle = RED;
    ctx.lineWidth = lineWidth;
    ctx.stroke();
  }

  ctx.strokeStyle = RED;
  ctx.lineWidth = lineWidth;
  ctx.strokeRect(px, py, bw * w, bh * h);

  const label = `${d.label} ${Math.round(d.confidence * 100)}%`;
  ctx.font = `600 ${fontSize}px ui-monospace, monospace`;
  const textWidth = ctx.measureText(label).width + 10;
  const labelY = py - fontSize - 6 >= 0 ? py - fontSize - 6 : py; // dans l'image même si la personne touche le haut
  ctx.fillStyle = RED;
  ctx.fillRect(px - lineWidth / 2, labelY, textWidth, fontSize + 6);
  ctx.fillStyle = '#fff';
  ctx.fillText(label, px + 4, labelY + fontSize);
}

// `meta` = en-tête reçu avec l'image : { annotated, detections, threat }
export function drawFrame(canvas, bitmap, meta) {
  const w = bitmap.width;
  const h = bitmap.height;
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  const ctx = canvas.getContext('2d');
  if (MIRROR) {
    ctx.save();
    ctx.translate(w, 0);
    ctx.scale(-1, 1);
    ctx.drawImage(bitmap, 0, 0);
    ctx.restore();
  } else {
    ctx.drawImage(bitmap, 0, 0);
  }

  const lineWidth = Math.max(2, Math.round(w / 300));
  const fontSize = Math.max(12, Math.round(w / 42));

  // meta.annotated : YOLO a déjà dessiné ses carrés dans l'image (VISION_ANNOTATE=1), on ne les double pas
  if (!meta.annotated) meta.detections.forEach((d) => drawBox(ctx, d, w, h, lineWidth, fontSize));

  ctx.font = `700 ${fontSize}px ui-monospace, monospace`;
  const persons = meta.personCount ?? meta.detections.length;
  if (persons > 0) {
    ctx.fillStyle = RED;
    ctx.fillText('INTRUSION DETECTED', 12, fontSize + 8);

    // menace : nombre de personnes détectées, en bandeau sous l'image
    const text = `${persons} PERSONNE${persons > 1 ? 'S' : ''} DÉTECTÉE${persons > 1 ? 'S' : ''}`;
    const barHeight = fontSize + 16;
    ctx.fillStyle = 'rgba(180, 20, 15, 0.88)';
    ctx.fillRect(0, h - barHeight, w, barHeight);
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'center';
    ctx.fillText(text, w / 2, h - barHeight / 2 + fontSize / 3);
    ctx.textAlign = 'start';
  }
  if (meta.threat) {
    const text = `MENACE ${meta.threat.score} · ${meta.threat.label}`;
    const textWidth = ctx.measureText(text).width + 16;
    ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
    ctx.fillRect(w - textWidth - 8, 8, textWidth, fontSize + 10);
    ctx.fillStyle = THREAT_COLORS[meta.threat.label] ?? '#fff';
    ctx.fillText(text, w - textWidth, fontSize + 14);
  }
}
