import { Button } from "@/components/ui/button";

interface ErrorStateProps {
  error: Error;
  reset: () => void;
}

export function ErrorState({ error, reset }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center space-y-4">
      <h2 className="text-2xl font-bold">Something went wrong!</h2>
      <p className="text-muted-foreground">{error.message}</p>
      <Button onClick={reset}>Try again</Button>
    </div>
  );
} 