import { NextRequest, NextResponse } from 'next/server';
import { memoryApiSecret, userIdFromMemoryCookie } from '@/lib/memory-auth';

const memoryApiUrl = process.env.MEMORY_API_URL ?? 'http://127.0.0.1:8001';

async function proxy(request: NextRequest, method: 'GET' | 'DELETE') {
  const userId = userIdFromMemoryCookie(request);
  if (!userId) return NextResponse.json({ error: 'Start a call first.' }, { status: 401 });
  try {
    const response = await fetch(memoryApiUrl, {
      method,
      headers: {
        'Content-Type': 'application/json',
        'X-Memory-User-Id': userId,
        'X-Memory-Secret': memoryApiSecret(),
      },
      body: method === 'DELETE' ? JSON.stringify(await request.json()) : undefined,
      cache: 'no-store',
    });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch (error) {
    console.error('Memory API request failed', error);
    return NextResponse.json(
      { error: 'Memory service is unavailable. Please try again shortly.' },
      { status: 503 }
    );
  }
}

export async function GET(request: NextRequest) {
  return proxy(request, 'GET');
}

export async function DELETE(request: NextRequest) {
  return proxy(request, 'DELETE');
}
