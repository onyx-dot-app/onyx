import React from "react";
import { TimelineRoot } from "@/lib/timeline/components/primitives/TimelineRoot";

export interface ResponseInsetProps {
  children?: React.ReactNode;
}

/**
 * An item of a response that is not a run card: answer text, the cursor, an
 * image or a card. A run card is a padded surface, so everything else punches
 * in to its content: the card's padding, its title's inset and its icon box's
 * padding, plus 1px because icon glyphs are drawn about 1px inside their box.
 * The item's start then lines up with the run card's visible icon.
 */
export function ResponseInset({ children }: ResponseInsetProps) {
  return (
    <TimelineRoot>
      <div className="ps-[calc(var(--spacing-inline-4)+var(--timeline-header-text-padding-x)+var(--padding-text-2)+1px)]">
        {children}
      </div>
    </TimelineRoot>
  );
}

export default ResponseInset;
