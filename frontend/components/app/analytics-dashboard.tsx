'use client';

import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';

type Analytics = {
  total_calls: number;
  successful_calls: number;
  failed_calls: number;
};

const emptyAnalytics: Analytics = { total_calls: 0, successful_calls: 0, failed_calls: 0 };

export function AnalyticsDashboard() {
  const [analytics, setAnalytics] = useState<Analytics>(emptyAnalytics);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/analytics', { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? 'Unable to load analytics.');
      setAnalytics(data);
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Unable to load analytics.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const metrics = [
    ['Total Calls', analytics.total_calls],
    ['Successful Calls', analytics.successful_calls],
    ['Failed Calls', analytics.failed_calls],
  ];

  return (
    <main className="mx-auto min-h-[calc(100svh-72px)] max-w-6xl px-5 py-10 md:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-primary text-sm font-semibold tracking-[0.14em] uppercase">Call analytics</p>
          <h1 className="text-foreground mt-2 text-3xl font-semibold tracking-[-0.03em]">Scheme enquiry outcomes</h1>
          <p className="text-muted-foreground mt-3 text-sm leading-6">Aggregate call counts only. No caller details or transcripts are displayed.</p>
        </div>
        <Button variant="outline" onClick={() => void load()} disabled={loading}>Refresh</Button>
      </div>
      {error ? <p className="text-destructive mt-6 text-sm">{error}</p> : null}
      <section className="mt-8 grid gap-4 md:grid-cols-3">
        {metrics.map(([label, value]) => (
          <article key={label as string} className="border-border rounded-2xl border p-6">
            <p className="text-muted-foreground text-sm font-medium">{label}</p>
            <p className="text-foreground mt-3 text-4xl font-semibold tabular-nums">{loading ? '—' : value}</p>
          </article>
        ))}
      </section>
    </main>
  );
}
