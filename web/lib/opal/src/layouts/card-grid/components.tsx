import { spacingToRem } from "@opal/shared";
import type { Spacing } from "@opal/types";

/**
 * A grid of cards, like the provider cards on the Language Models page: one
 * column, and two once the grid itself is wide enough. It measures its own
 * width (a container query), not the viewport's, so it fits any column.
 */
interface CardGridProps {
  children?: React.ReactNode;
  /** Space between the cards, as a spacing step (`N / 4` rem). @default 2 */
  gap?: Spacing;
}

function CardGrid({ children, gap = 2 }: CardGridProps) {
  return (
    <div className="@container/card-grid w-full">
      <div
        className="grid grid-cols-1 @xl/card-grid:grid-cols-2"
        style={{ gap: spacingToRem(gap) }}
      >
        {children}
      </div>
    </div>
  );
}

export { CardGrid, type CardGridProps };
