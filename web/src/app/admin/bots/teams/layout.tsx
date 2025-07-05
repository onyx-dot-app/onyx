import { ReactNode } from "react";

interface TeamsBotLayoutProps {
  children: ReactNode;
}

export default function TeamsBotLayout({ children }: TeamsBotLayoutProps) {
  return (
    <div className="container mx-auto py-8">
      <div className="space-y-8">
        <div>
          <h1 className="text-3xl font-bold">Teams Bots</h1>
          <p className="text-muted-foreground">
            Manage your Teams bots and channel configurations
          </p>
        </div>
        {children}
      </div>
    </div>
  );
} 