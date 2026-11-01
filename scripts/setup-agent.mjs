import { randomBytes } from 'node:crypto';
import { appendFileSync, existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const path = resolve('.env.local');
const current = existsSync(path) ? readFileSync(path, 'utf8') : '';
const defaults = {
  FOLIO_INTERNAL_SECRET: randomBytes(32).toString('hex'),
  FOLIO_SESSION_SECRET: randomBytes(32).toString('hex'),
  FOLIO_FRONTEND_URL: 'http://localhost:3000',
  PYTHON_AGENT_URL: 'http://localhost:8000',
};
const entries = Object.entries(defaults).filter(([name]) => !new RegExp(`^${name}=`, 'm').test(current));
if (entries.length) appendFileSync(path, `\n${entries.map(([key, value]) => `${key}=${value}`).join('\n')}\n`, { mode: 0o600 });
console.info('Folio local agent configuration is ready. No credentials are printed.');
