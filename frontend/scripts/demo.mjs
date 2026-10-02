/** Portable, explicit demo build/run. Does not alter .env or reveal credentials. */
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../../', import.meta.url));
const vite = fileURLToPath(new URL('../../node_modules/vite/bin/vite.js', import.meta.url));
const env = { ...process.env, DEMO_MODE: 'true' };
const command = process.argv[2] || 'start';
function run(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [vite, ...args, '--config', 'frontend/vite.config.ts'], { cwd: root, env, stdio: 'inherit', windowsHide: true });
    child.on('error', reject);
    child.on('exit', code => code === 0 ? resolve() : reject(new Error(`Demo command exited ${code}`)));
  });
}
try {
  if (command === 'dev') await run(['frontend']);
  else {
    await run(['build', 'frontend']);
    if (command !== 'build') await run(['preview', 'frontend', '--host', '127.0.0.1', '--port', '5181']);
  }
} catch (error) { console.error(error.message); process.exitCode = 1; }
