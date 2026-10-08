// Provider réel : le Raspberry Pi, joint par SSH. Même contrat que mockProvider.js :
//   name                      : string
//   start(onSnapshot)         : lance la collecte, appelle onSnapshot(snapshot) à chaque tick
//   stop()                    : arrête la collecte et ferme la connexion
//   getSnapshot()             : dernier snapshot connu
//   sendMotorCommand(cmd)     : valide la commande (motor.js), l'envoie au Pi, retourne l'état moteur
//
// Forme du snapshot (identique au mock ; `thermal` vaut null sans matrice AMG8833) :
//   { ts, ultrasonic:{distanceCm,maxRangeCm}, thermal:{avgC,maxC,grid[8][8]}|null,
//     camera:{streamUrl,width,height,fps}, motor:{angle,target,speed,mode,moving},
//     environment:{tempC,humidityPct,readAt},   // DHT22
//     system:{link,cpuPct,ramPct,cpuTempC,uptimeS} }
//
// Côté Pi : pi/sentinel_agent.py, lancé par SSH. Il écrit un snapshot JSON par ligne sur stdout et lit
// les commandes moteur (JSON, une par ligne) sur stdin. Le Pi n'envoie que de la donnée BRUTE.
// Mode local (AGENT_LOCAL=1) : l'agent est lancé en --fake sur ce PC, sans Raspberry (test du protocole ;
// SENTINEL_CAMERA_CMD permet d'y brancher une source vidéo, voir pi/camera_stream.py).
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { Client } from 'ssh2';
import { applyMotorCommand } from './motor.js';

const RETRY_MS = [1000, 2000, 5000, 10000];
const LOCAL_AGENT = fileURLToPath(new URL('../../../pi/sentinel_agent.py', import.meta.url));

const shellQuote = (s) => `'${String(s).replace(/'/g, `'\\''`)}'`;

export function createSshProvider(options, { tickMs = 1000 } = {}) {
  let latest = null;
  let onSnapshotCb = null;
  let session = null; // { stdin: Writable, close: () => void }
  let retry = 0;
  let timer = null;
  let stopped = false;

  // Flux vidéo : le Pi sert du MJPEG sur --stream-port ; le dashboard l'ouvre directement (pas de passage par le serveur).
  const streamUrl = options.camera ? options.streamUrl || `http://${options.host}:${options.streamPort}/stream.mjpg` : '';
  const agentArgs = [
    `--period ${tickMs / 1000}`,
    ...(options.camera ? ['--camera', `--stream-port ${options.streamPort}`] : []),
    ...(streamUrl ? [`--stream-url ${shellQuote(streamUrl)}`] : []),
  ];

  function feed(stdout) {
    let buffer = '';
    stdout.on('data', (chunk) => {
      buffer += chunk.toString('utf8');
      let nl;
      while ((nl = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;
        try {
          latest = JSON.parse(line);
          onSnapshotCb?.(latest);
        } catch (err) {
          console.warn(`[ssh] ligne illisible ignorée : ${err.message}`);
        }
      }
    });
  }

  function scheduleReconnect(reason) {
    session = null;
    if (stopped) return;
    const delay = RETRY_MS[Math.min(retry, RETRY_MS.length - 1)];
    retry += 1;
    console.warn(`[ssh] Pi indisponible (${reason}), nouvelle tentative dans ${delay / 1000} s`);
    timer = setTimeout(connect, delay);
  }

  function connectLocal() {
    const child = spawn('python3', [LOCAL_AGENT, '--fake', '--period', String(tickMs / 1000),
      ...(options.camera ? ['--camera', '--stream-port', String(options.streamPort), '--stream-url', `http://localhost:${options.streamPort}/stream.mjpg`] : [])], { stdio: ['pipe', 'pipe', 'inherit'] });
    session = { stdin: child.stdin, close: () => child.kill() };
    child.stdin.on('error', () => {});
    feed(child.stdout);
    child.on('close', (code) => scheduleReconnect(`agent local arrêté (${code})`));
    retry = 0;
  }

  function connectSsh() {
    const conn = new Client();
    let privateKey;
    try {
      if (options.privateKeyPath) privateKey = readFileSync(options.privateKeyPath);
    } catch (err) {
      console.error(`[ssh] clé privée illisible (${options.privateKeyPath}) : ${err.message}`);
    }
    conn
      .on('ready', () => {
        const command = `${options.command} ${agentArgs.join(' ')}`;
        conn.exec(command, (err, stream) => {
          if (err) return conn.end();
          retry = 0;
          console.log(`[ssh] connecté à ${options.host}, agent lancé`);
          session = { stdin: stream.stdin ?? stream, close: () => conn.end() };
          feed(stream);
          stream.stderr.on('data', (d) => process.stderr.write(d));
          stream.on('close', () => conn.end());
        });
      })
      .on('error', (err) => scheduleReconnect(err.message))
      .on('close', () => {
        if (session) scheduleReconnect('connexion fermée');
      })
      .connect({
        host: options.host,
        port: options.port,
        username: options.username,
        privateKey,
        password: options.password || undefined,
        keepaliveInterval: 5000,
        readyTimeout: 8000,
      });
  }

  function connect() {
    if (stopped) return;
    options.local ? connectLocal() : connectSsh();
  }

  return {
    name: options.local ? 'agent local (fake)' : 'ssh',

    start(onSnapshot) {
      onSnapshotCb = onSnapshot;
      connect();
    },

    stop() {
      stopped = true;
      clearTimeout(timer);
      session?.close();
    },

    getSnapshot: () => latest,

    // Retourne l'état moteur attendu ; lève une Error si la commande est invalide ou le Pi injoignable.
    async sendMotorCommand(cmd) {
      if (!session) throw new Error('Raspberry Pi non connecté');
      const motor = { mode: 'manual', angle: 0, target: 0, speed: 40, moving: false, ...latest?.motor };
      applyMotorCommand(motor, cmd);
      session.stdin.write(`${JSON.stringify(cmd)}\n`);
      return motor;
    },
  };
}
