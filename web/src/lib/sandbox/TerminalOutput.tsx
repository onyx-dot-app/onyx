import { richNodes } from "@opal/utils";
import type { RichNodes } from "@opal/types";
import { terminalSpans } from "@/lib/sandbox/terminalSpans";

/** Terminal output as styled nodes for `CodePanel.Output`. */
export function terminalOutputNodes(text: string): RichNodes {
  return richNodes(
    terminalSpans(text).map((span, index) =>
      span.style === null ? (
        span.text
      ) : (
        <span key={index} style={span.style}>
          {span.text}
        </span>
      )
    )
  );
}
