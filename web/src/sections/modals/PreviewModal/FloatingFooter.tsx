import { cn } from "@/lib/utils";
import { ReactNode } from "react";

interface FloatingFooterProps {
  left?: ReactNode;
  right?: ReactNode;
  codeBackground?: boolean;
}

export default function FloatingFooter({
  left,
  right,
  codeBackground,
}: FloatingFooterProps) {
  return (
    <div
      className={cn(
        "absolute bottom-0 left-0 right-0",
        "flex items-center justify-between",
        "p-4 pointer-events-none w-full"
      )}
      style={{
        background: `linear-gradient(to top, var(--background-${
          codeBackground ? "code-01" : "tint-01"
        }) 40%, transparent)`,
      }}
    >
      {/* Left slot */}
      <div className="pointer-events-auto">{left}</div>

      {/* Right slot */}
      {right ? (
        <div className="pointer-events-auto rounded-12 bg-background-tint-00 p-1 shadow-lg">
          {right}
        </div>
      ) : null}
    </div>
  );
}
