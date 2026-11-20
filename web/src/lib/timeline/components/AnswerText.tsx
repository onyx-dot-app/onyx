import React from "react";
import { TimelineRoot } from "@/lib/timeline/components/primitives/TimelineRoot";

export interface AnswerTextProps {
  children?: React.ReactNode;
}

/**
 * Answer text between runs. Its start lines up with the run header's text:
 * the header surface's padding plus the header text's own inset.
 */
export function AnswerText({ children }: AnswerTextProps) {
  return (
    <TimelineRoot>
      <div className="ps-[calc(var(--spacing-inline-4)+var(--timeline-header-text-padding-x))]">
        {children}
      </div>
    </TimelineRoot>
  );
}

export default AnswerText;
