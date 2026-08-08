'use client';

import { useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { useSessionContext } from '@livekit/components-react';
import type { AppConfig } from '@/app-config';
import {
  ConnectingView,
  EndedView,
  FinanceSessionView,
  MicrophoneErrorView,
} from '@/components/app/finance-session-view';
import { WelcomeView } from '@/components/app/welcome-view';

type ViewState = 'ready' | 'connecting' | 'active' | 'ended' | 'microphone-error';

function isMicrophoneAccessError(error: unknown) {
  if (!(error instanceof Error)) return false;
  return ['NotAllowedError', 'PermissionDeniedError', 'SecurityError'].includes(error.name);
}

export function ViewController({ appConfig }: { appConfig: AppConfig }) {
  const session = useSessionContext();
  const [attemptedConnection, setAttemptedConnection] = useState(false);
  const [endedByUser, setEndedByUser] = useState(false);
  const [microphoneError, setMicrophoneError] = useState(false);

  const start = async () => {
    setMicrophoneError(false);
    setEndedByUser(false);
    setAttemptedConnection(true);
    try {
      await session.start();
    } catch (error) {
      if (isMicrophoneAccessError(error)) setMicrophoneError(true);
    }
  };

  const end = async () => {
    setEndedByUser(true);
    await session.end();
  };

  const startAgain = () => {
    setAttemptedConnection(false);
    setEndedByUser(false);
    setMicrophoneError(false);
  };

  let view: ViewState = 'ready';
  if (microphoneError) view = 'microphone-error';
  else if (session.isConnected) view = 'active';
  else if (endedByUser) view = 'ended';
  else if (attemptedConnection) view = 'connecting';

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={view}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
      >
        {view === 'ready' && (
          <WelcomeView startButtonText={appConfig.startButtonText} onStartCall={start} />
        )}
        {view === 'connecting' && <ConnectingView />}
        {view === 'active' && (
          <FinanceSessionView
            onEnd={end}
            onMicrophoneError={(error) => setMicrophoneError(isMicrophoneAccessError(error))}
          />
        )}
        {view === 'ended' && <EndedView onStartAgain={startAgain} />}
        {view === 'microphone-error' && <MicrophoneErrorView onTryAgain={start} />}
      </motion.div>
    </AnimatePresence>
  );
}
