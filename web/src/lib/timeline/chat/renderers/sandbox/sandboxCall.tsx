import type { ReactNode } from "react";
import { Section } from "@opal/layouts";
import { ShadowDiv, Text } from "@opal/components";
import { RenderType } from "@/app/app/message/messageComponents/types";

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
    <Section gap={2} alignItems="stretch" height="fit">
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
        {error}
      </Text>
    </div>
  );
}
