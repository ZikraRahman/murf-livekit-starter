'use client';

import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';

type Memory = { name?: string | null; language_preference?: string | null; facts?: Record<string, string> };

export function SettingsView() {
  const [memory, setMemory] = useState<Memory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/memory', { cache: 'no-store' });
      const data = await response.json();
      setMemory(data.memory ?? null);
      setError(response.ok ? null : data.error ?? 'Unable to load memories.');
    } catch {
      setMemory(null);
      setError('Unable to load memories. Please try again.');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const remove = async (key: string, all = false) => {
    if (all && !window.confirm('Forget all saved memories? This cannot be undone.')) return;
    await fetch('/api/memory', { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(all ? { all: true } : { key }) });
    await load();
  };
  const items = [
    ...(memory?.name ? [{ key: 'name', label: 'Name', value: memory.name }] : []),
    ...(memory?.language_preference ? [{ key: 'language_preference', label: 'Language preference', value: memory.language_preference }] : []),
    ...Object.entries(memory?.facts ?? {}).map(([key, value]) => ({ key, label: key, value })),
  ];
  return (
    <main className="mx-auto min-h-[calc(100svh-72px)] max-w-2xl px-5 py-10 md:px-8">
      <p className="text-primary text-sm font-semibold tracking-[0.14em] uppercase">Settings</p>
      <h1 className="text-foreground mt-2 text-3xl font-semibold tracking-[-0.03em]">Memories</h1>
      <p className="text-muted-foreground mt-3 text-sm leading-6">Only information you approved for saving appears here.</p>
      <section className="border-border mt-8 divide-y rounded-2xl border">
        {loading ? <p className="text-muted-foreground p-5 text-sm">Loading memories…</p> : error ? <p className="text-muted-foreground p-5 text-sm">{error}</p> : items.length === 0 ? <p className="text-muted-foreground p-5 text-sm">No saved memories yet.</p> : items.map((item) => (
          <div key={item.key} className="flex items-center gap-4 p-5">
            <div className="min-w-0 flex-1"><p className="text-muted-foreground text-xs font-semibold uppercase">{item.label}</p><p className="text-foreground mt-1 break-words text-sm">{item.value}</p></div>
            <Button variant="ghost" className="text-destructive" onClick={() => void remove(item.key)}>Delete</Button>
          </div>
        ))}
      </section>
      <section className="border-border mt-8 rounded-2xl border p-5"><h2 className="text-foreground font-semibold">Forget all memories</h2><p className="text-muted-foreground mt-1 text-sm">Permanently remove everything saved for this browser.</p><Button variant="destructive" className="mt-4" onClick={() => void remove('', true)}>Forget all memories</Button></section>
      <section className="border-border mt-5 rounded-2xl border p-5"><h2 className="text-foreground font-semibold">Appearance</h2><p className="text-muted-foreground mt-1 text-sm">Use the theme control in the header.</p></section>
      <section className="border-border mt-5 rounded-2xl border p-5"><h2 className="text-foreground font-semibold">Language</h2><p className="text-muted-foreground mt-1 text-sm">Language settings are coming soon.</p></section>
    </main>
  );
}
