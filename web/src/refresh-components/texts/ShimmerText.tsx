import { Text } from "@opal/components";
import type { RichStr } from "@opal/types";

interface ShimmerTextProps {
  children: string | RichStr;
}

/**
 * Status text with a shimmer sweep, used while an agent streams.
 *
 * Renders the text twice: the visible base text and an inert clone that is
 * masked to its own glyphs (`-webkit-mask-clip: text`). A highlight bar
 * slides across the clone with a transform animation, so the effect runs on
 * the compositor instead of repainting the text every frame. The clone (vs.
 * a pseudo-element on the base text) avoids sub-pixel thinning of the
 * glyphs. Styles live in `globals.css` (`.shimmer-text`).
 *
 * Technique: https://codepen.io/editor/devongovett/pen/01a0439c-4b7f-7f44-bf84-205c514ad139
 */
export default function ShimmerText({ children }: ShimmerTextProps) {
  return (
    <div className="shimmer-text">
      <Text as="p" font="main-ui-action" color="inherit">
        {children}
      </Text>
      <div aria-hidden="true" inert className="shimmer-text-overlay">
        <Text as="p" font="main-ui-action" color="inherit">
          {children}
        </Text>
      </div>
    </div>
  );
}
