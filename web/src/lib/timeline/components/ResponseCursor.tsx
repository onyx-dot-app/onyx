import { Section } from "@opal/layouts";
import { BlinkingBar } from "@/app/app/message/BlinkingBar";

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

export default ResponseCursor;
