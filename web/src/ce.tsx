"use client";

import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/interfaces/settings";
import { ComponentType, ReactNode, createElement } from "react";

/**
 * Passthrough component — renders children as-is, effectively a no-op wrapper.
 * <A><Invisible><B/></Invisible></A> === <A><B/></A>
 */
function Invisible({ children }: { children?: ReactNode }) {
  return <>{children}</>;
}

/**
 * Gates a component behind any paid tier (BUSINESS or ENTERPRISE).
 * Returns the real component on a paid tier, or `Invisible` (passthrough)
 * on Community.
 *
 * For providers: Community renders Invisible, so children pass through
 * and downstream hooks fall back to their context defaults.
 *
 * For leaf components: Community renders Invisible with no children,
 * so nothing is rendered.
 *
 * Note: this is a coarse outer gate ("is the tenant paying?"). For
 * Enterprise-only features, callers should also gate on
 * `useTierAtLeast(Tier.ENTERPRISE)` downstream.
 */
export function paidTierGated<P extends {}>(
  Component: ComponentType<P>
): ComponentType<P> {
  function PaidTierGatedWrapper(props: P) {
    const isPaidTier = useTierAtLeast(Tier.BUSINESS);
    if (!isPaidTier)
      return (
        <Invisible>{(props as { children?: ReactNode }).children}</Invisible>
      );
    return createElement(Component, props);
  }
  PaidTierGatedWrapper.displayName = `paidTierGated(${
    Component.displayName || Component.name || "Component"
  })`;
  return PaidTierGatedWrapper;
}
