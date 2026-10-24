/**
 * A grid of cards, like the provider cards on the Language Models page: one
 * column, and two once the grid itself is wide enough. It measures its own
 * width (a container query), not the viewport's, so it fits any column.
 */
interface CardGridProps {
  children?: React.ReactNode;
}

function CardGrid({ children }: CardGridProps) {
  return (
    <div className="@container/card-grid w-full">
      <div className="grid grid-cols-1 gap-2 @xl/card-grid:grid-cols-2">
        {children}
      </div>
    </div>
  );
}

export { CardGrid, type CardGridProps };
