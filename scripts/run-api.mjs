// Lance l'API avec le Python du venv (backend/.venv) sans avoir à l'activer.
//   node scripts/run-api.mjs           mode mock
//   node scripts/run-api.mjs --yolo    YOLO sur la webcam du navigateur (équivalent de la config F5 par défaut)
// Port : API_PORT (défaut 4000). Les variables ANALYZER, VISION_SOURCE, YOLO_MODEL... déjà définies sont respectées.
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const backend = join(root, 'backend');
const python =
  process.platform === 'win32' ? join(backend, '.venv', 'Scripts', 'python.exe') : join(backend, '.venv', 'bin', 'python');

if (!existsSync(python)) {
  console.error(`Venv Python introuvable : ${python}\n`);
  console.error('Créez-le une fois :');
  console.error('  cd backend');
  console.error('  python -m venv .venv');
  console.error(process.platform === 'win32' ? '  .venv\\Scripts\\activate' : '  source .venv/bin/activate');
  console.error('  pip install -r requirements.txt -r requirements-vision.txt');
  process.exit(1);
}

const env = { ...process.env };
if (process.argv.includes('--yolo')) {
  env.ANALYZER ??= 'local';
  env.VISION_SOURCE ??= 'browser';
  env.YOLO_MODEL ??= 'yolov8n-seg.pt';
  env.YOLO_IMGSZ ??= '480';
}

const args = ['-m', 'uvicorn', 'app.main:app', '--reload', '--reload-dir', 'app', '--port', String(env.API_PORT ?? 4000)];
const child = spawn(python, args, { cwd: backend, env, stdio: 'inherit' });
child.on('exit', (code) => process.exit(code ?? 0));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
