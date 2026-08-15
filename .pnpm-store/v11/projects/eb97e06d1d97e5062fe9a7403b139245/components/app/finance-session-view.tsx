'use client';

import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { type Participant, RoomEvent, Track } from 'livekit-client';
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
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/shadcn/utils';

type FinanceSessionViewProps = {
  onEnd: () => void;
  onMicrophoneError: (error: Error) => void;
};

type ActiveAgent = 'main' | 'personal_finance' | 'tax_gst';

const ACTIVE_AGENT_ATTRIBUTE = 'bharat_finance.active_agent';

const AGENT_PRESENTATION = {
  main: {
    name: 'BHARAT FINANCE ASSISTANT',
    subtitle: 'Your financial assistant',
    badge: '● Bharat Finance Assistant',
    accent: 'bg-primary',
    text: 'text-primary',
    ring: 'ring-primary/35',
    button: 'bg-primary text-primary-foreground',
    orbBackground: 'radial-gradient(circle at 32% 28%, #49bf87 0%, #16855b 42%, #0f6242 100%)',
    orbGlow: '0 0 42px rgb(22 133 91 / 35%)',
  },
  personal_finance: {
    name: 'PERSONAL FINANCE SPECIALIST',
    subtitle: 'Budget & Savings',
    badge: '● Personal Finance Specialist',
    accent: 'bg-blue-500',
    text: 'text-blue-500',
    ring: 'ring-blue-500/45',
    button: 'bg-blue-500 text-white hover:bg-blue-600',
    orbBackground: 'radial-gradient(circle at 32% 28%, #93c5fd 0%, #3b82f6 42%, #1d4ed8 100%)',
    orbGlow: '0 0 42px rgb(59 130 246 / 35%)',
  },
  tax_gst: {
    name: 'TAX & GST SPECIALIST',
    subtitle: 'ITR & GST Guidance',
    badge: '● Tax & GST Specialist',
    accent: 'bg-yellow-400',
    text: 'text-yellow-500',
    ring: 'ring-yellow-400/50',
    button: 'bg-yellow-400 text-slate-950 hover:bg-yellow-300',
    orbBackground: 'radial-gradient(circle at 32% 28%, #fde68a 0%, #facc15 42%, #ca8a04 100%)',
    orbGlow: '0 0 42px rgb(250 204 21 / 40%)',
  },
} as const;

function getActiveAgent(value?: string): ActiveAgent | undefined {
  if (value === 'main') {
    return 'main';
  }
  if (value === 'personal_finance') {
    return 'personal_finance';
  }
  if (value === 'tax_gst') {
    return 'tax_gst';
  }
  return undefined;
}

function isConnectingAgent(value?: string) {
  return (
    value === 'connecting_main' ||
    value === 'connecting_personal_finance' ||
    value === 'connecting_tax_gst'
  );
}

function VoiceOrb({
  muted = false,
  ring,
  background,
  glow,
}: {
  muted?: boolean;
  ring?: string;
  background?: string;
  glow?: string;
}) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        'relative grid size-48 place-items-center rounded-[44%_56%_55%_45%/48%_43%_57%_52%] md:size-56',
        muted ? 'finance-orb-muted' : 'finance-orb',
        ring && `ring-4 ${ring}`
      )}
      style={background && glow ? { background, boxShadow: glow } : undefined}
    >
      <span className="absolute inset-[12%] rounded-[55%_45%_42%_58%/42%_58%_45%_55%] bg-white/12" />
      <span className="absolute inset-[27%] rounded-full bg-white/10" />
    </div>
  );
}

function AgentWaveform({ accent }: { accent: string }) {
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
          className={cn('w-1.5 rounded-full transition-[height] duration-75 ease-out', accent)}
          style={{ height: `${Math.max(10, Math.min(100, value * 180 + 10))}%` }}
        />
      ))}
    </div>
  );
}

function Transcript({
  messages,
  assistantMessageAgents,
  fallbackAgent,
}: {
  messages: ReceivedMessage[];
  assistantMessageAgents: Record<string, ActiveAgent>;
  fallbackAgent: ActiveAgent;
}) {
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
          {messages.map(({ id, from, message }) => {
            const messageAgent = assistantMessageAgents[id] ?? fallbackAgent;
            const presentation = AGENT_PRESENTATION[messageAgent];

            return (
              <article key={id} className="space-y-1.5">
                <p
                  className={cn(
                    'text-xs font-bold tracking-[0.12em] uppercase',
                    from?.isLocal ? 'text-primary' : presentation.text
                  )}
                >
                  {from?.isLocal ? 'You' : presentation.name}
                </p>
                <p className="text-foreground text-sm leading-6">{message}</p>
              </article>
            );
          })}
          <div ref={endRef} />
        </div>
      )}
    </section>
  );
}

function TextInput({
  onClose,
  buttonClassName,
  textClassName,
}: {
  onClose: () => void;
  buttonClassName: string;
  textClassName: string;
}) {
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
          className={buttonClassName}
        >
          <Send />
        </Button>
      </form>
      <button
        type="button"
        onClick={onClose}
        className={cn('mt-2 px-2 text-sm font-medium', textClassName)}
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
  const [activeAgent, setActiveAgent] = useState<ActiveAgent>('main');
  const [publishedAgent, setPublishedAgent] = useState<string>('main');
  const [assistantMessageAgents, setAssistantMessageAgents] = useState<
    Record<string, ActiveAgent>
  >({});

  useEffect(() => {
    const applyActiveAgent = (value: string | undefined, participant: Participant) => {
      const derivedAgent = getActiveAgent(value);
      console.log('[ACTIVE_AGENT_DEBUG] participant:', participant.identity);
      console.log('[ACTIVE_AGENT_DEBUG] attributes:', participant.attributes);
      console.log('[ACTIVE_AGENT_DEBUG] active_agent:', value);
      console.log('[ACTIVE_AGENT_DEBUG] derivedAgent:', derivedAgent ?? 'unknown');

      if (!value) {
        console.warn(
          '[ACTIVE_AGENT_DEBUG] Unknown active-agent value; retaining current UI state.',
          {
            participant: participant.identity,
            value,
          }
        );
        return;
      }

      setPublishedAgent(value);
      if (isConnectingAgent(value)) {
        return;
      }

      if (!derivedAgent) {
        console.warn(
          '[ACTIVE_AGENT_DEBUG] Unknown active-agent value; retaining current UI state.',
          {
            participant: participant.identity,
            value,
          }
        );
        return;
      }

      setActiveAgent(derivedAgent);
    };

    const logParticipants = () => {
      console.log('[ACTIVE_AGENT_DEBUG] local participant:', {
        identity: session.room.localParticipant.identity,
        attributes: session.room.localParticipant.attributes,
      });
      for (const participant of session.room.remoteParticipants.values()) {
        console.log('[ACTIVE_AGENT_DEBUG] remote participant:', {
          identity: participant.identity,
          attributes: participant.attributes,
        });
      }
    };

    const syncParticipant = (participant: Participant) => {
      const value = participant.attributes[ACTIVE_AGENT_ATTRIBUTE];
      if (value !== undefined) {
        applyActiveAgent(value, participant);
        return true;
      }
      return false;
    };

    const syncPublishedAgent = () => {
      logParticipants();
      if (syncParticipant(session.room.localParticipant)) {
        return;
      }
      for (const participant of session.room.remoteParticipants.values()) {
        if (syncParticipant(participant)) {
          return;
        }
      }
    };

    const handleParticipantAttributesChanged = (
      changedAttributes: Record<string, string>,
      participant: Participant
    ) => {
      const value = changedAttributes[ACTIVE_AGENT_ATTRIBUTE];
      console.log('[ACTIVE_AGENT_DEBUG] participant:', participant.identity);
      console.log('[ACTIVE_AGENT_DEBUG] changed attributes:', changedAttributes);
      console.log('[ACTIVE_AGENT_DEBUG] changed attributes JSON:', JSON.stringify(changedAttributes));
      console.log('[ACTIVE_AGENT_DEBUG] attributes:', participant.attributes);
      console.log('[ACTIVE_AGENT_DEBUG] attributes JSON:', JSON.stringify(participant.attributes));
      console.log('[ACTIVE_AGENT_DEBUG] active_agent:', value);
      console.log('[ACTIVE_AGENT_DEBUG] active_agent value:', String(value));
      console.log('[ACTIVE_AGENT_DEBUG] derivedAgent:', getActiveAgent(value) ?? 'unknown');
      if (Object.hasOwn(changedAttributes, ACTIVE_AGENT_ATTRIBUTE)) {
        applyActiveAgent(value, participant);
      }
    };

    syncPublishedAgent();
    session.room.on(RoomEvent.Connected, syncPublishedAgent);
    session.room.on(RoomEvent.ParticipantConnected, syncParticipant);
    session.room.on(RoomEvent.ParticipantAttributesChanged, handleParticipantAttributesChanged);
    return () => {
      session.room.off(RoomEvent.Connected, syncPublishedAgent);
      session.room.off(RoomEvent.ParticipantConnected, syncParticipant);
      session.room.off(RoomEvent.ParticipantAttributesChanged, handleParticipantAttributesChanged);
    };
  }, [session.room]);

  useEffect(() => {
    setAssistantMessageAgents((current) => {
      let changed = false;
      const next = { ...current };

      for (const { id, from } of messages) {
        if (!from?.isLocal && next[id] === undefined) {
          next[id] = activeAgent;
          changed = true;
        }
      }

      return changed ? next : current;
    });
  }, [activeAgent, messages]);

  const presentation = AGENT_PRESENTATION[activeAgent];
  const connectingLabel =
    publishedAgent === 'connecting_personal_finance'
      ? 'Connecting to Personal Finance Specialist...'
      : publishedAgent === 'connecting_tax_gst'
        ? 'Connecting to Tax & GST Specialist...'
        : publishedAgent === 'connecting_main'
          ? 'Connecting to Bharat Finance Assistant...'
          : null;
  const speaking = agentState === 'speaking';
  const status = speaking
    ? 'Your agent is speaking'
    : agentState === 'thinking'
      ? 'Your agent is preparing an answer'
      : 'Your agent is listening';

  return (
    <div className="bg-background min-h-svh">
      <main className="mx-auto grid min-h-[calc(100svh-72px)] max-w-6xl gap-8 px-5 py-8 lg:grid-cols-[minmax(0,1.15fr)_minmax(320px,.85fr)] lg:items-center lg:px-8">
        <section className="flex flex-col items-center justify-center text-center">
          <div className="flex h-64 items-center justify-center md:h-72">
            {speaking ? (
              <AgentWaveform accent={presentation.accent} />
            ) : (
              <VoiceOrb
                ring={presentation.ring}
                background={presentation.orbBackground}
                glow={presentation.orbGlow}
              />
            )}
          </div>
          <div className="mt-3 space-y-1">
            <p className="text-foreground text-lg font-semibold tracking-[0.08em] uppercase">
              {presentation.name}
            </p>
            <p className="text-muted-foreground text-sm">{presentation.subtitle}</p>
            <p
              className={cn(
                'text-xs font-semibold',
                connectingLabel ? 'text-muted-foreground' : presentation.text
              )}
            >
              {connectingLabel ?? presentation.badge}
            </p>
          </div>
          <h1 className="text-foreground mt-5 text-2xl font-semibold tracking-[-0.03em]">
            {status}
          </h1>
          <p className="text-muted-foreground mt-2 text-sm">
            {speaking ? 'Please wait a moment' : 'Go ahead, I’m listening'}
          </p>

          <div className="mt-8 flex w-full max-w-md flex-col gap-3">
            {isTyping ? (
              <TextInput
                onClose={() => setIsTyping(false)}
                buttonClassName={presentation.button}
                textClassName={presentation.text}
              />
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
        <Transcript
          messages={messages}
          assistantMessageAgents={assistantMessageAgents}
          fallbackAgent={activeAgent}
        />
      </main>
    </div>
  );
}

export function ConnectingView() {
  return (
    <div className="bg-background min-h-svh">
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
