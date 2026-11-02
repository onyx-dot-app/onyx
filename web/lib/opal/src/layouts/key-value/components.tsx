import type { RichStr } from "@opal/types";
import { OverflowText } from "@opal/components";

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
 * One read-only "label … value" row. Each side is capped at the form's input
 * column width, and a long label or value is cut with its full text on hover.
 */
function KeyValue({ label, value, mono = false }: KeyValueProps) {
  return (
    <div className="flex w-full flex-row gap-4">
      <div className="min-w-0 max-w-(--block-width-form-input-column-max)">
        <OverflowText as="p" font="main-ui-action" color="text-03">
          {label}
        </OverflowText>
      </div>
      <div className="ms-auto min-w-0 max-w-(--block-width-form-input-column-max) flex-1 text-end">
        <OverflowText
          as="p"
          font={mono ? "main-ui-mono" : "main-ui-body"}
          color="text-04"
        >
          {value}
        </OverflowText>
      </div>
    </div>
  );
}

export { KeyValue, type KeyValueProps };
