import './setup-agent.mjs';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';

const python = existsSync('.venv/bin/python') ? '.venv/bin/python' : 'python3';
const agent = spawn(python, ['-m', 'uvicorn', 'backend.server:app', '--host', '0.0.0.0', '--port', '8000'], { stdio: 'inherit', env: process.env });
const ui = spawn('pnpm', ['exec', 'next', 'dev', '--hostname', '0.0.0.0', '--port', '3000'], { stdio: 'inherit', env: process.env });
const stop = () => { agent.kill('SIGTERM'); ui.kill('SIGTERM'); };
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
ui.on('exit', code => { agent.kill('SIGTERM'); process.exit(code ?? 0); });
agent.on('error', () => console.error('Python agent could not start. Install backend/requirements.txt in a Python environment.'));
