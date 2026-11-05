// Keep npm run dev as an entry point for the Flask dashboard.
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const appDir = dirname(fileURLToPath(import.meta.url));
const repo = resolve(appDir, '../..');
const localPython = resolve(repo, process.platform === 'win32'
  ? '.venv-web/Scripts/python.exe' : '.venv-web/bin/python');
const python = process.env.WEB_PYTHON || (existsSync(localPython)
  ? localPython : process.platform === 'win32' ? 'python' : 'python3');
const child = spawn(python, [resolve(appDir, 'app.py')], { cwd: repo, stdio: 'inherit' });
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', code => { process.exitCode = code ?? 1; });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
