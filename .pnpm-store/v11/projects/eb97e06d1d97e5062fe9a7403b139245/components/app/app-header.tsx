'use client';

import { Menu, MessageSquare, Settings, X } from 'lucide-react';
import { useState } from 'react';
import { ThemeToggle } from '@/components/app/theme-toggle';
import { Button } from '@/components/ui/button';

type AppHeaderProps = { onHome: () => void; onSettings: () => void };

export function AppHeader({ onHome, onSettings }: AppHeaderProps) {
  const [open, setOpen] = useState(false);
  const navigate = (action: () => void) => {
    action();
    setOpen(false);
  };
  return (
    <header className="border-border/80 bg-background/90 sticky top-0 z-20 flex h-[72px] items-center justify-between border-b px-5 backdrop-blur-sm md:px-8">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" aria-label="Open navigation" onClick={() => setOpen(true)}>
          <Menu size={20} />
        </Button>
        <p className="text-foreground text-sm font-semibold tracking-[-0.02em] md:text-base">
          <span className="text-primary mr-1.5">₹</span>Bharat Finance Assistant
        </p>
      </div>
      <ThemeToggle />
      {open && (
        <div className="bg-background/40 fixed inset-0 z-30" onClick={() => setOpen(false)}>
          <aside className="border-border bg-background h-full w-80 border-r p-5 shadow-xl" onClick={(event) => event.stopPropagation()}>
            <div className="mb-8 flex items-center justify-between">
              <span className="font-semibold">Menu</span>
              <Button variant="ghost" size="icon" aria-label="Close navigation" onClick={() => setOpen(false)}><X size={20} /></Button>
            </div>
            <nav className="space-y-2">
              <Button variant="ghost" className="w-full justify-start" onClick={() => navigate(onHome)}><Menu size={17} />Home</Button>
              <Button variant="ghost" className="w-full justify-start" disabled><MessageSquare size={17} />Conversations <span className="text-muted-foreground ml-auto text-xs">Soon</span></Button>
              <Button variant="ghost" className="w-full justify-start" onClick={() => navigate(onSettings)}><Settings size={17} />Settings</Button>
            </nav>
          </aside>
        </div>
      )}
    </header>
  );
}
