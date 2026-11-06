import type { RichStr } from "@opal/types";
import { Text } from "@opal/components";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface KeyValueProps {
  /** The name of the value, on the start side. */
  label: string | RichStr;

  /** The value, on the end side. */
  value: string | RichStr;

  /** Sets the value in the mono font, as for a secret, a commit or an id. */
  mono?: boolean;
}

// ---------------------------------------------------------------------------
// KeyValue
// ---------------------------------------------------------------------------

/**
 * One read-only "label … value" row. Both sides wrap rather than cut, so the
 * full text shows to every user, with no hover needed. The label takes at
 * most half the row, so the value always keeps room.
 */
function KeyValue({ label, value, mono = false }: KeyValueProps) {
  return (
    <div className="flex w-full flex-row gap-4">
      <div className="min-w-0 max-w-[min(50%,var(--block-width-form-input-column-max))] [overflow-wrap:anywhere]">
        <Text as="p" font="main-ui-action" color="text-03">
          {label}
        </Text>
      </div>
      <div className="ms-auto min-w-0 max-w-(--block-width-form-input-column-max) flex-1 text-end [overflow-wrap:anywhere]">
        <Text
          as="p"
          font={mono ? "main-ui-mono" : "main-ui-body"}
          color="text-04"
        >
          {value}
        </Text>
      </div>
    </div>
  );
}

export { KeyValue, type KeyValueProps };
