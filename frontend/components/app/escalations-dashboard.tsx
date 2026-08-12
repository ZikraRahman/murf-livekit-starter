'use client';

import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';

type Escalation = {
  reference_id: string;
  who_needs_help: string;
  what_happened: string;
  what_agent_checked: string;
  urgency: string;
  caller_language: string;
  preferred_follow_up: string;
  status: string;
  created_at: string;
};

function formatTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

export function EscalationsDashboard() {
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/escalations', { cache: 'no-store' });
      const data = await response.json();
      setEscalations(data.escalations ?? []);
      setError(response.ok ? null : data.error ?? 'Unable to load escalations.');
    } catch {
      setEscalations([]);
      setError('Unable to load escalations. Please try again.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <main className="mx-auto min-h-[calc(100svh-72px)] max-w-6xl px-5 py-10 md:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-primary text-sm font-semibold tracking-[0.14em] uppercase">
            Human support
          </p>
          <h1 className="text-foreground mt-2 text-3xl font-semibold tracking-[-0.03em]">
            Open escalations
          </h1>
          <p className="text-muted-foreground mt-3 text-sm leading-6">
            Requests submitted by the finance assistant for human review.
          </p>
        </div>
        <Button variant="outline" onClick={() => void load()} disabled={loading}>
          Refresh
        </Button>
      </div>

      <section className="border-border mt-8 overflow-hidden rounded-2xl border">
        {loading ? (
          <p className="text-muted-foreground p-5 text-sm">Loading open escalations…</p>
        ) : error ? (
          <p className="text-destructive p-5 text-sm">{error}</p>
        ) : escalations.length === 0 ? (
          <p className="text-muted-foreground p-5 text-sm">No open escalation requests.</p>
        ) : (
          <div className="divide-border divide-y">
            {escalations.map((escalation) => (
              <article key={escalation.reference_id} className="p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-foreground font-mono text-sm font-semibold">
                      {escalation.reference_id}
                    </p>
                    <p className="text-muted-foreground mt-1 text-sm">
                      {escalation.who_needs_help} · {formatTime(escalation.created_at)}
                    </p>
                  </div>
                  <span className="bg-primary/10 text-primary rounded-full px-3 py-1 text-xs font-semibold uppercase">
                    {escalation.status}
                  </span>
                </div>
                <dl className="mt-5 grid gap-4 text-sm md:grid-cols-2">
                  <div>
                    <dt className="text-muted-foreground text-xs font-semibold uppercase">Issue</dt>
                    <dd className="text-foreground mt-1 leading-6">{escalation.what_happened}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground text-xs font-semibold uppercase">Agent checked</dt>
                    <dd className="text-foreground mt-1 leading-6">{escalation.what_agent_checked}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground text-xs font-semibold uppercase">Urgency</dt>
                    <dd className="text-foreground mt-1">{escalation.urgency}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground text-xs font-semibold uppercase">Caller language</dt>
                    <dd className="text-foreground mt-1">{escalation.caller_language}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground text-xs font-semibold uppercase">Preferred follow-up</dt>
                    <dd className="text-foreground mt-1">{escalation.preferred_follow_up}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
