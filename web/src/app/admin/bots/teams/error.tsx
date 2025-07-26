import { useEffect } from "react";
import { Button } from "@/components/ui/button";

interface TeamsBotErrorPageProps {
  error: Error;
  reset: () => void;
}

export default function TeamsBotErrorPage({
  error,
  reset,
}: TeamsBotErrorPageProps) {
  useEffect(() => {
    console.error("Teams bot error:", error);
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center space-y-4">
      <h2 className="text-2xl font-bold">Something went wrong!</h2>
      <p className="text-muted-foreground">{error.message}</p>
      <Button onClick={reset}>Try again</Button>
    </div>
  );
} 