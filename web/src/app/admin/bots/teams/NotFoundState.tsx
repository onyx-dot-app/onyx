import { Button } from "@/components/ui/button";
import Link from "next/link";

export function NotFoundState() {
  return (
    <div className="flex flex-col items-center justify-center space-y-4">
      <h2 className="text-2xl font-bold">Teams Bot Not Found</h2>
      <p className="text-muted-foreground">
        The Teams bot you are looking for does not exist.
      </p>
      <Button asChild>
        <Link href="/admin/bots/teams">Back to Teams Bots</Link>
      </Button>
    </div>
  );
} 