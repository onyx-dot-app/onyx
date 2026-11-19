import type { ReactNode } from "react";
import { Section } from "@opal/layouts";
import { ShadowDiv, Text } from "@opal/components";
import { RenderType } from "@/app/app/message/messageComponents/types";

// Embedding, override and isolate controls, and the directional marks.
const BIDI_CONTROLS = /[\u202A-\u202E\u2066-\u2069\u200E\u200F\u061C]/g;

/** Text from the sandbox (a path, an error) in its own Unicode isolate, with
 * its bidi controls removed, so it cannot reorder the text around it. */
export function isolateText(text: string): string {
  return `\u2068${text.replace(BIDI_CONTROLS, "")}\u2069`;
}

interface SandboxCallContentProps {
  renderType: RenderType;
  children: ReactNode;
}

/** The body of a sandbox call step; the collapsed view shows its top. */
export function SandboxCallContent({
  renderType,
  children,
}: SandboxCallContentProps) {
  const content = (
    <Section gap={1} alignItems="stretch" height="fit">
      {children}
    </Section>
  );
  return renderType === RenderType.FULL ? (
    content
  ) : (
    <ShadowDiv
      shadowDirection="bottom-only"
      variant="mask"
      shadowHeight={8}
      className="max-h-24 overflow-hidden"
    >
      {content}
    </ShadowDiv>
  );
}

interface SandboxCallErrorProps {
  error: string;
}

export function SandboxCallError({ error }: SandboxCallErrorProps) {
  return (
    <div className="whitespace-pre-wrap wrap-break-word">
      <Text as="p" font="secondary-body" color="status-error-05">
        {isolateText(error)}
      </Text>
    </div>
  );
}
