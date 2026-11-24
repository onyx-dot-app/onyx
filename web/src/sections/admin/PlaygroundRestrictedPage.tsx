"use client";

import { MessageCard, ReadOnlyRegion } from "@opal/components";
import { SvgLock } from "@opal/icons";
import { Section } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { usePlaygroundRestriction } from "@/lib/playground/hooks";
import type { PlaygroundRestrictedFeature } from "@/lib/playground/types";

export interface PlaygroundRestrictedPageProps {
  /** The page's feature key. `undefined` renders the children as they are. */
  featureKey: PlaygroundRestrictedFeature | undefined;
  children: React.ReactNode;
}

/**
 * An admin page the playground restricts: the page stays on screen but
 * nothing on it can be used, under one notice that says why and points to
 * sales. The region is inert, so no editor or popup can open from it.
 * Off the playground, and for a feature that is not restricted, the
 * children render as they are.
 *
 * This is the plain version. The visual pass from the trial-states design
 * replaces this one component.
 */
export default function PlaygroundRestrictedPage({
  featureKey,
  children,
}: PlaygroundRestrictedPageProps) {
  const { loading, restricted, title, description } =
    usePlaygroundRestriction(featureKey);
  // A page with a feature key waits for the settings: it must not be live
  // for a moment before the page knows it is restricted.
  if (featureKey !== undefined && loading) {
    return (
      <Section padding={8}>
        <IconLoader className="h-6 w-6" />
      </Section>
    );
  }
  if (!restricted) return <>{children}</>;

  return (
    <Section
      justifyContent="start"
      alignItems="stretch"
      gap={0}
      height="auto"
      data-testid="playground-restricted-page"
    >
      <Section padding={4} height="auto">
        <MessageCard icon={SvgLock} title={title} description={description} />
      </Section>
      <ReadOnlyRegion>{children}</ReadOnlyRegion>
    </Section>
  );
}
