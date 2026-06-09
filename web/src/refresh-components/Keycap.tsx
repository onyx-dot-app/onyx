import { Text } from "@opal/components";
import { cn } from "@opal/utils";

interface KeycapProps {
  children: string;
  /** Filled state for active shortcut hints. */
  filled?: boolean;
}

/**
 * A small boxed keyboard-key glyph (e.g. `esc`, `↵`, `⌫`) for inline shortcut
 * hints. The `filled` state renders a stronger neutral cap.
 */
export default function Keycap({ children, filled = false }: KeycapProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-08 border px-1 leading-none transition-colors duration-150",
        filled
          ? "border-border-03 bg-background-tint-03"
          : "border-border-02 bg-background-tint-02"
      )}
    >
      <Text font="secondary-body" color={filled ? "text-04" : "text-02"}>
        {children}
      </Text>
    </span>
  );
}
