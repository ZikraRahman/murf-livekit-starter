import { createHmac, timingSafeEqual } from 'crypto';
import type { NextRequest } from 'next/server';

export const MEMORY_COOKIE_NAME = 'bharat-memory-user';

function secret(): string {
  const value = process.env.LIVEKIT_API_SECRET;
  if (!value) throw new Error('LIVEKIT_API_SECRET is not defined');
  return value;
}

export function signedUserCookie(userId: string): string {
  return `${userId}.${createHmac('sha256', secret()).update(userId).digest('base64url')}`;
}

export function userIdFromMemoryCookie(request: NextRequest): string | null {
  const value = request.cookies.get(MEMORY_COOKIE_NAME)?.value;
  if (!value) return null;
  const separator = value.lastIndexOf('.');
  if (separator < 1) return null;
  const userId = value.slice(0, separator);
  const signature = value.slice(separator + 1);
  const expected = signedUserCookie(userId).slice(separator + 1);
  const actual = Buffer.from(signature);
  const expectedValue = Buffer.from(expected);
  return actual.length === expectedValue.length && timingSafeEqual(actual, expectedValue)
    ? userId
    : null;
}

export function memoryApiSecret(): string {
  return secret();
}
