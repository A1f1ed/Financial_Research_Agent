import { NextRequest, NextResponse } from 'next/server';
import { createSession, SESSION_COOKIE, verifySession } from './lib/folio-session';

export function proxy(request: NextRequest) {
  if (verifySession(request.cookies.get(SESSION_COOKIE)?.value)) return NextResponse.next();
  const session = createSession();
  const headers = new Headers(request.headers);
  const existing = headers.get('cookie')?.split(';').filter(v => !v.trim().startsWith(`${SESSION_COOKIE}=`)).join(';') ?? '';
  headers.set('cookie', `${existing}${existing ? '; ' : ''}${SESSION_COOKIE}=${session.token}`);
  const response = NextResponse.next({ request: { headers } });
  const secure = request.nextUrl.protocol === 'https:' || request.headers.get('x-forwarded-proto') === 'https';
  response.cookies.set(SESSION_COOKIE, session.token, { httpOnly: true, secure, sameSite: secure ? 'none' : 'lax', maxAge: session.maxAge, path: '/' });
  return response;
}
export const config = { matcher: ['/((?!_next/static|_next/image|favicon.ico|api/agent/model).*)'] };
