import { Button } from '@/components/ui/button';

interface WelcomeViewProps {
  startButtonText: string;
  onStartCall: () => void;
}

export const WelcomeView = ({
  startButtonText,
  onStartCall,
  ref,
}: React.ComponentProps<'div'> & WelcomeViewProps) => (
  <div ref={ref}>
    <section className="flex min-h-[calc(100svh-72px)] flex-col items-center justify-center px-6 text-center">
      <p className="text-primary mb-4 text-sm font-semibold tracking-[0.18em] uppercase">
        ₹ Finance, made friendly
      </p>
      <h1 className="text-foreground max-w-xl text-4xl font-semibold tracking-[-0.04em] md:text-6xl">
        Bharat Finance Assistant
      </h1>
      <p className="text-muted-foreground mt-5 max-w-md text-base leading-7 md:text-lg">
        Your everyday voice guide for money decisions
      </p>
      <p className="text-muted-foreground mt-3 text-sm">Budget · Savings · UPI · Banking</p>
      <Button
        size="lg"
        onClick={onStartCall}
        className="mt-9 h-12 rounded-xl px-6 text-base font-semibold"
      >
        {startButtonText}
      </Button>
    </section>
  </div>
);
