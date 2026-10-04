"use client";

import "@opal/loaders/styles.css";
import { Card, type CardProps } from "@opal/components";
import { useOpalStrings } from "@opal/strings";

/** Every plain-mode `Card` prop except the body, which the loader fills. */
type CardLoaderCardProps = Omit<
  Extract<CardProps, { expandable?: false }>,
  "children" | "expandable"
>;

type CardLoaderProps = CardLoaderCardProps & {
  /** Description lines under the title. @default 1 */
  descriptionLines?: number;
};

/**
 * A card that has not loaded: a card holding a shimmering icon, title and
 * description, in the shape of a `ContentAction` card. The card takes every
 * `Card` prop; unset, it is a solid-bordered card with `rounding={4}` and
 * `padding={4}`, like the setup and catalog cards.
 */
function CardLoader({
  descriptionLines = 1,
  border = "solid",
  rounding = 4,
  padding = 4,
  ...cardProps
}: CardLoaderProps) {
  const strings = useOpalStrings();
  return (
    <div role="status" aria-label={strings.loading} className="w-full">
      <Card
        {...cardProps}
        border={border}
        rounding={rounding}
        padding={padding}
      >
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
