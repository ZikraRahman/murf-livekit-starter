import { NextResponse } from 'next/server';
import { memoryApiSecret } from '@/lib/memory-auth';

const memoryApiUrl = process.env.MEMORY_API_URL ?? 'http://127.0.0.1:8001';

export async function GET() {
  try {
    const response = await fetch(`${memoryApiUrl}/escalations`, {
      headers: { 'X-Memory-Secret': memoryApiSecret() },
      cache: 'no-store',
    });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch (error) {
    console.error('Escalations API request failed', error);
    return NextResponse.json(
      { error: 'Escalation service is unavailable. Please try again shortly.' },
      { status: 503 }
    );
  }
}
