import { Section } from "@opal/layouts";
import { cn } from "@opal/utils";
import {
  RESPONSE_CURSOR_ANCHOR_ATTRIBUTE,
  STREAMING_CURSOR_CLASS_NAME,
} from "@/lib/rehypeStreamingCursor";
import {
  RESPONSE_CURSOR_KEY,
  type ResponseItem,
} from "@/lib/timeline/components/Response";

interface ResponseCursorAnchorProps {
  /**
   * A waiting `slot` or `text`. The cursor glides when it moves between the
   * two, and follows text at once.
   */
  kind?: "slot" | "text";
  addMargin?: boolean;
}

/**
 * Marks where the response's one cursor sits (see `Response`). It has the
 * cursor's box, so the cursor lands where an inline cursor would be.
 */
export function ResponseCursorAnchor({
  kind = "text",
  addMargin = false,
}: ResponseCursorAnchorProps) {
  return (
    <span
      aria-hidden
      {...{ [RESPONSE_CURSOR_ANCHOR_ATTRIBUTE]: kind }}
      className={cn(
        STREAMING_CURSOR_CLASS_NAME,
        "invisible",
        addMargin && "ms-1"
      )}
    />
  );
}

/**
 * The slot the cursor waits in while a turn works with nothing streaming:
 * after a send, before the first packet, and under a run, also while its
 * steps run. Chat and Craft both use it. It is one run header tall, so a run
 * card takes its place without a jump; text that takes its place carries the
 * cursor on.
 */
export function ResponseCursor() {
  return (
    <Section flexDirection="row" justifyContent="start" height={2.25} gap={0}>
      <ResponseCursorAnchor kind="slot" />
    </Section>
  );
}

/**
 * The cursor slot as a response item. A send mounts the response with the
 * slot already in it, so its space opens rather than snapping.
 */
export function responseCursorItem(): ResponseItem {
  return {
    kind: "text",
    key: RESPONSE_CURSOR_KEY,
    node: <ResponseCursor />,
    appear: true,
  };
}

export default ResponseCursor;
