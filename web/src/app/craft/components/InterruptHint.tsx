import { Text } from "@opal/components";
import Keycap from "@/refresh-components/Keycap";

interface InterruptHintProps {
  /** Interrupt requested, awaiting the turn to terminate. */
  interrupting: boolean;
}

/**
 * The streaming-only hint that teaches the Esc interrupt. Once an interrupt is
 * requested it becomes `Stopping…`.
 */
export default function InterruptHint({ interrupting }: InterruptHintProps) {
  if (interrupting) {
    return (
      <Text font="secondary-body" color="text-02">
        Stopping…
      </Text>
    );
  }

  return (
    <div className="flex items-center gap-1 select-none">
      <Keycap>esc</Keycap>
      <Text font="secondary-body" color="text-02">
        to interrupt
      </Text>
    </div>
  );
}
