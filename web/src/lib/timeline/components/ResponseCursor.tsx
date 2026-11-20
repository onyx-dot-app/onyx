import { Section } from "@opal/layouts";
import { BlinkingBar } from "@/app/app/message/BlinkingBar";
import type { ResponseItem } from "@/lib/timeline/components/Response";

/**
 * The cursor a response shows while it works with nothing to show yet: after
 * a send, before the first packet. Chat and Craft both use it. It is one run
 * header tall, so the first run card takes its place without a jump.
 */
export function ResponseCursor() {
  return (
    <Section flexDirection="row" justifyContent="start" height={2.25} gap={0}>
      <BlinkingBar />
    </Section>
  );
}

/**
 * The cursor as a response item. A send mounts the response with the cursor
 * already in it, so it fades in rather than flashing.
 */
export function responseCursorItem(): ResponseItem {
  return {
    kind: "text",
    key: "cursor",
    node: <ResponseCursor />,
    appear: true,
  };
}

export default ResponseCursor;
