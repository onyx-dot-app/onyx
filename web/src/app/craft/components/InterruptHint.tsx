import { Text } from "@opal/components";
import Keycap from "@/refresh-components/Keycap";

interface InterruptHintProps {
  /** First Esc pressed — the next Esc within the window interrupts. */
  armed: boolean;
  /** Interrupt requested, awaiting the turn to terminate. */
  interrupting: boolean;
}

/**
 * The streaming-only hint that teaches the double-Esc interrupt. At rest it
 * reads `esc ×2 to interrupt`; the first Esc lights the keycap; once an
 * interrupt is requested it becomes `Stopping…`.
 */
export default function InterruptHint({
  armed,
  interrupting,
}: InterruptHintProps) {
  if (interrupting) {
    return (
      <Text font="secondary-body" color="text-02">
        Stopping…
      </Text>
    );
  }

  return (
    <div className="flex items-center gap-1 select-none">
      <Keycap filled={armed}>esc</Keycap>
      <Text font="secondary-body" color="text-02">
        ×2 to interrupt
      </Text>
    </div>
  );
}
