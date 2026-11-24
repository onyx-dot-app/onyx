import { createContext, useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Section } from "@opal/layouts";
import { cn } from "@opal/utils";

/**
 * Where a host puts a preview's actions instead of over its bottom, such as
 * the chat panel's URL bar. Null keeps them in the footer.
 */
export const PreviewActionsSlotContext = createContext<HTMLElement | null>(
  null
);

interface FloatingFooterProps {
  left?: ReactNode;
  right?: ReactNode;
  codeBackground?: boolean;
}

/**
 * A preview's actions, over the bottom of its content on a fading background.
 * With a host slot, the right-hand actions go to the slot instead.
 */
export default function FloatingFooter({
  left,
  right,
  codeBackground,
}: FloatingFooterProps) {
  const slot = useContext(PreviewActionsSlotContext);
  const moved = slot !== null && right ? createPortal(right, slot) : null;
  const floating = moved ? null : right;
  if (!left && !floating) return moved;
  return (
    <>
      {moved}
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
        {floating ? (
          <div className="pointer-events-auto rounded-12 bg-background-tint-00 p-1 shadow-lg">
            {floating}
          </div>
        ) : null}
      </Section>
    </>
  );
}
