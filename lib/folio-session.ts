import { createHmac, randomUUID, timingSafeEqual } from 'node:crypto';

export const SESSION_COOKIE = 'folio_workspace';
const maxAge = 60 * 60 * 24 * 30;
function signingSecret() {
  const value = process.env.FOLIO_SESSION_SECRET;
  if (!value || value.length < 32) throw new Error('FOLIO_SESSION_SECRET must be configured with at least 32 characters.');
  return value;
}
function signature(value: string) { return createHmac('sha256', signingSecret()).update(value).digest('base64url'); }
export function verifySession(token: string | undefined): string | null {
  if (!token) return null;
  const [id, expires, mac, extra] = token.split('.');
  if (extra || !id || !/^[a-f0-9-]{36}$/.test(id) || !/^\d{10}$/.test(expires ?? '') || !mac || Number(expires) <= Date.now() / 1000) return null;
  const expected = Buffer.from(signature(`${id}.${expires}`));
  const supplied = Buffer.from(mac);
  return expected.length === supplied.length && timingSafeEqual(expected, supplied) ? id : null;
}
export function createSession() {
  const id = randomUUID();
  const value = `${id}.${Math.floor(Date.now() / 1000) + maxAge}`;
  return { id, token: `${value}.${signature(value)}`, maxAge };
}
export function userFromRequest(request: Request) {
  const token = request.headers.get('cookie')?.split(';').map(v => v.trim()).find(v => v.startsWith(`${SESSION_COOKIE}=`))?.slice(SESSION_COOKIE.length + 1);
  const id = verifySession(token);
  if (!id) throw new Error('A valid workspace session is required. Refresh the page to create one.');
  return { id, name: 'Folio 访客工作空间' };
}
export function internalAuthorized(request: Request) {
  const secret = process.env.FOLIO_INTERNAL_SECRET;
  if (!secret || secret.length < 32) return false;
  const actual = Buffer.from(request.headers.get('authorization') ?? '');
  const expected = Buffer.from(`Bearer ${secret}`);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}
export function sameOrigin(request: Request) {
  const origin = request.headers.get('origin');
  if (!origin) return true;
  try { return new URL(origin).host === (request.headers.get('x-forwarded-host') ?? request.headers.get('host') ?? new URL(request.url).host); }
  catch { return false; }
}
