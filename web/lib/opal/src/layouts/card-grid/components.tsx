import { spacingToRem } from "@opal/shared";
import type { Spacing } from "@opal/types";
import { cn } from "@opal/utils";

const columnsClassMap = {
  "one-to-two": "grid-cols-1 @xl/card-grid:grid-cols-2",
  "two-to-three": "grid-cols-2 @[24rem]/card-grid:grid-cols-3",
} as const;

/**
 * A grid of cards, like the provider cards on the Language Models page. Its
 * column count grows with the grid's own width (a container query), not the
 * viewport's, so it fits any column; `columns` picks the steps.
 */
interface CardGridProps {
  children?: React.ReactNode;
  /** Space between the cards, as a spacing step (`N / 4` rem). @default 2 */
  gap?: Spacing;
  /**
   * `"one-to-two"`: one column, two once the grid is 36rem wide.
   * `"two-to-three"`: two columns, three once the grid is 24rem wide, for
   * small tiles. @default "one-to-two"
   */
  columns?: keyof typeof columnsClassMap;
}

function CardGrid({
  children,
  gap = 2,
  columns = "one-to-two",
}: CardGridProps) {
  return (
    <div className="@container/card-grid w-full">
      <div
        className={cn("grid", columnsClassMap[columns])}
        style={{ gap: spacingToRem(gap) }}
      >
        {children}
      </div>
    </div>
  );
}

export { CardGrid, type CardGridProps };
