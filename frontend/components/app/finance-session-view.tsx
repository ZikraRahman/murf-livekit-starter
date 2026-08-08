'use client';

import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { Track } from 'livekit-client';
import { Mic, MicOff, Send, Square, Volume2 } from 'lucide-react';
import {
  type ReceivedMessage,
  useAgent,
  useAudioWaveform,
  useChat,
  useSessionContext,
  useSessionMessages,
  useTrackToggle,
  useVoiceAssistant,
} from '@livekit/components-react';
import { ThemeToggle } from '@/components/app/theme-toggle';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/shadcn/utils';

type FinanceSessionViewProps = {
  onEnd: () => void;
  onMicrophoneError: (error: Error) => void;
};

function BrandHeader() {
  return (
    <header className="border-border/80 bg-background/90 sticky top-0 z-20 flex h-[72px] items-center justify-between border-b px-5 backdrop-blur-sm md:px-8">
      <p className="text-foreground text-sm font-semibold tracking-[-0.02em] md:text-base">
        <span className="text-primary mr-1.5">₹</span>Bharat Finance Assistant
      </p>
      <ThemeToggle />
    </header>
  );
}

function VoiceOrb({ muted = false }: { muted?: boolean }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        'relative grid size-48 place-items-center rounded-[44%_56%_55%_45%/48%_43%_57%_52%] md:size-56',
        muted ? 'finance-orb-muted' : 'finance-orb'
      )}
    >
      <span className="absolute inset-[12%] rounded-[55%_45%_42%_58%/42%_58%_45%_55%] bg-white/12" />
      <span className="absolute inset-[27%] rounded-full bg-white/10" />
    </div>
  );
}

function AgentWaveform() {
  const { audioTrack } = useVoiceAssistant();
  const { bars } = useAudioWaveform(audioTrack, {
    barCount: 36,
    updateInterval: 50,
    volMultiplier: 1.6,
  });
  const displayedBars = useMemo(
    () => (bars.length ? bars : Array.from({ length: 36 }, () => 0.04)),
    [bars]
  );

  return (
    <div
      className="flex h-44 w-full max-w-xl items-center justify-center gap-1.5 px-4"
      aria-label="Agent audio waveform"
    >
      {displayedBars.map((value, index) => (
        <span
          key={index}
          className="bg-primary w-1.5 rounded-full transition-[height] duration-75 ease-out"
          style={{ height: `${Math.max(10, Math.min(100, value * 180 + 10))}%` }}
        />
      ))}
    </div>
  );
}

function Transcript({ messages }: { messages: ReceivedMessage[] }) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  return (
    <section
      aria-label="Live conversation"
      className="finance-transcript flex min-h-0 flex-1 flex-col rounded-2xl border p-4 md:p-5"
    >
      <p className="text-muted-foreground mb-4 text-xs font-semibold tracking-[0.14em] uppercase">
        Conversation
      </p>
      {messages.length === 0 ? (
        <p className="text-muted-foreground text-sm leading-6">
          Your live conversation will appear here.
        </p>
      ) : (
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto pr-1">
          {messages.map(({ id, from, message }) => (
            <article key={id} className="space-y-1.5">
              <p className="text-primary text-xs font-bold tracking-[0.12em] uppercase">
                {from?.isLocal ? 'You' : 'Bharat Finance Assistant'}
              </p>
              <p className="text-foreground text-sm leading-6">{message}</p>
            </article>
          ))}
          <div ref={endRef} />
        </div>
      )}
    </section>
  );
}

function TextInput({ onClose }: { onClose: () => void }) {
  const { send } = useChat();
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = message.trim();
    if (!trimmed || sending) return;
    setSending(true);
    try {
      await send(trimmed);
      setMessage('');
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="finance-input rounded-2xl border p-3">
      <form onSubmit={handleSubmit} className="flex items-center gap-2">
        <input
          autoFocus
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="Type your message..."
          className="text-foreground placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent px-2 py-2 text-sm outline-none"
        />
        <Button
          type="submit"
          size="icon"
          aria-label="Send message"
          disabled={!message.trim() || sending}
        >
          <Send />
        </Button>
      </form>
      <button
        type="button"
        onClick={onClose}
        className="text-primary mt-2 px-2 text-sm font-medium"
      >
        🎙 Talk instead
      </button>
    </div>
  );
}

export function FinanceSessionView({ onEnd, onMicrophoneError }: FinanceSessionViewProps) {
  const session = useSessionContext();
  const { state: agentState } = useAgent();
  const { messages } = useSessionMessages(session);
  const microphone = useTrackToggle({
    source: Track.Source.Microphone,
    onDeviceError: onMicrophoneError,
  });
  const [isTyping, setIsTyping] = useState(false);
  const speaking = agentState === 'speaking';
  const status = speaking
    ? 'Your agent is speaking'
    : agentState === 'thinking'
      ? 'Your agent is preparing an answer'
      : 'Your agent is listening';

  return (
    <div className="bg-background min-h-svh">
      <BrandHeader />
      <main className="mx-auto grid min-h-[calc(100svh-72px)] max-w-6xl gap-8 px-5 py-8 lg:grid-cols-[minmax(0,1.15fr)_minmax(320px,.85fr)] lg:items-center lg:px-8">
        <section className="flex flex-col items-center justify-center text-center">
          <div className="flex h-64 items-center justify-center md:h-72">
            {speaking ? <AgentWaveform /> : <VoiceOrb />}
          </div>
          <h1 className="text-foreground mt-5 text-2xl font-semibold tracking-[-0.03em]">
            {status}
          </h1>
          <p className="text-muted-foreground mt-2 text-sm">
            {speaking ? 'Please wait a moment' : 'Go ahead, I’m listening'}
          </p>

          <div className="mt-8 flex w-full max-w-md flex-col gap-3">
            {isTyping ? (
              <TextInput onClose={() => setIsTyping(false)} />
            ) : (
              <Button
                variant="outline"
                onClick={() => setIsTyping(true)}
                className="h-11 rounded-xl font-medium"
              >
                💬 Type instead
              </Button>
            )}
            <div className="grid grid-cols-2 gap-3">
              <Button
                variant="outline"
                onClick={() => microphone.toggle()}
                aria-pressed={microphone.enabled}
                className="h-11 rounded-xl font-medium"
              >
                {microphone.enabled ? <Mic size={18} /> : <MicOff size={18} />}
                {microphone.enabled ? 'Mute microphone' : 'Enable microphone'}
              </Button>
              <Button
                variant="destructive"
                onClick={onEnd}
                className="h-11 rounded-xl font-semibold"
              >
                <Square size={16} fill="currentColor" /> End Call
              </Button>
            </div>
          </div>
        </section>
        <Transcript messages={messages} />
      </main>
    </div>
  );
}

export function ConnectingView() {
  return (
    <div className="bg-background min-h-svh">
      <BrandHeader />
      <main className="flex min-h-[calc(100svh-72px)] flex-col items-center justify-center px-6 text-center">
        <VoiceOrb muted />
        <h1 className="text-foreground mt-8 text-2xl font-semibold tracking-[-0.03em]">
          Your agent is joining...
        </h1>
        <p className="text-muted-foreground mt-2 text-sm">Please wait a moment</p>
      </main>
    </div>
  );
}

export function EndedView({ onStartAgain }: { onStartAgain: () => void }) {
  return (
    <div className="bg-background min-h-svh">
      <BrandHeader />
      <main className="flex min-h-[calc(100svh-72px)] flex-col items-center justify-center px-6 text-center">
        <div className="bg-primary/12 text-primary grid size-14 place-items-center rounded-full text-3xl">
          ✓
        </div>
        <h1 className="text-foreground mt-6 text-3xl font-semibold tracking-[-0.03em]">
          Conversation ended
        </h1>
        <p className="text-muted-foreground mt-3 max-w-sm leading-6">
          Thanks for talking with Bharat Finance Assistant.
        </p>
        <Button onClick={onStartAgain} className="mt-8 h-11 rounded-xl px-6 font-semibold">
          Start Again
        </Button>
      </main>
    </div>
  );
}

export function MicrophoneErrorView({ onTryAgain }: { onTryAgain: () => void }) {
  return (
    <div className="bg-background min-h-svh">
      <BrandHeader />
      <main className="flex min-h-[calc(100svh-72px)] flex-col items-center justify-center px-6 text-center">
        <div className="bg-primary/12 text-primary grid size-14 place-items-center rounded-full">
          <Volume2 />
        </div>
        <h1 className="text-foreground mt-6 text-3xl font-semibold tracking-[-0.03em]">
          Microphone access needed
        </h1>
        <p className="text-muted-foreground mt-3 max-w-md leading-6">
          Your browser is blocking microphone access, so I can’t hear you.
        </p>
        <ol className="text-muted-foreground mt-6 max-w-sm list-inside list-decimal space-y-2 text-left text-sm leading-6">
          <li>Open your browser’s site settings</li>
          <li>Allow microphone access</li>
          <li>Return here</li>
          <li>Try again</li>
        </ol>
        <Button onClick={onTryAgain} className="mt-8 h-11 rounded-xl px-6 font-semibold">
          Try Again
        </Button>
      </main>
    </div>
  );
}
