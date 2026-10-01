"use client";

import "@opal/loaders/styles.css";
import { Card } from "@opal/components";
import { useOpalStrings } from "@opal/strings";

interface CardLoaderProps {
  /** Description lines under the title. @default 1 */
  descriptionLines?: number;
}

/**
 * A card that has not loaded: a bordered card holding a shimmering icon,
 * title and description, in the shape of a `ContentAction` card.
 */
function CardLoader({ descriptionLines = 1 }: CardLoaderProps) {
  const strings = useOpalStrings();
  return (
    <div role="status" aria-label={strings.loading} className="w-full">
      <Card border="solid" rounding={4} padding={4}>
        <div className="flex w-full flex-row items-start gap-3">
          <div className="opal-shimmer-block size-5 shrink-0 rounded-full" />
          <div className="flex w-full flex-col gap-2 pt-1">
            <div className="opal-shimmer-block h-3 w-1/3 rounded-04" />
            {Array.from({ length: descriptionLines }, (_, index) => (
              <div
                key={index}
                className={
                  index === descriptionLines - 1
                    ? "opal-shimmer-block h-3 w-2/3 rounded-04"
                    : "opal-shimmer-block h-3 w-full rounded-04"
                }
              />
            ))}
          </div>
        </div>
      </Card>
    </div>
  );
}

export { CardLoader, type CardLoaderProps };
