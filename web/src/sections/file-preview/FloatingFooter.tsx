import type { ReactNode } from "react";
import { Section } from "@opal/layouts";
import { cn } from "@opal/utils";

interface FloatingFooterProps {
  left?: ReactNode;
  right?: ReactNode;
  codeBackground?: boolean;
}

/** A preview's actions, over the bottom of its content on a fading background. */
export default function FloatingFooter({
  left,
  right,
  codeBackground,
}: FloatingFooterProps) {
  return (
    <Section
      flexDirection="row"
      justifyContent="between"
      height="auto"
      padding={4}
      className={cn(
        "absolute bottom-0 start-0 end-0 pointer-events-none",
        "bg-linear-to-t from-40% to-transparent",
        codeBackground
          ? "from-background-code-01"
          : "from-background-neutral-00"
      )}
    >
      <div className="pointer-events-auto">{left}</div>
      {right ? (
        <div className="pointer-events-auto rounded-12 bg-background-tint-00 p-1 shadow-lg">
          {right}
        </div>
      ) : null}
    </Section>
  );
}
