import { Section } from "@opal/layouts";
import { CardLoader } from "@opal/loaders/card-loader/components";

interface CardLoadersProps {
  /** How many cards to show. @default 3 */
  count?: number;
}

/** A vertical list of transparent, borderless `CardLoader`s, for a list of cards that has not loaded. */
function CardLoaders({ count = 3 }: CardLoadersProps) {
  return (
    <Section alignItems="stretch" height="fit" gap={2}>
      {Array.from({ length: count }, (_, index) => (
        <CardLoader key={index} color="transparent" border="none" />
      ))}
    </Section>
  );
}

export { CardLoaders, type CardLoadersProps };
