"use client";

import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { ComponentType, ReactNode, createElement } from "react";

/**
 * Passthrough component — renders children as-is, effectively a no-op wrapper.
 * <A><Invisible><B/></Invisible></A> === <A><B/></A>
 */
function Invisible({ children }: { children?: ReactNode }) {
  return <>{children}</>;
}

/**
 * Gates a component behind Enterprise. Returns the real component for EE,
 * or Invisible (passthrough) for CE.
 *
 * For providers: Community renders Invisible, so children pass through
 * and downstream hooks fall back to their context defaults.
 *
 * For leaf components: Community renders Invisible with no children,
 * so nothing is rendered.
 */
export function eeGated<P extends {}>(
  EEComponent: ComponentType<P>
): ComponentType<P> {
  function EEGatedWrapper(props: P) {
    const isEnterprise = usePaidEnterpriseFeaturesEnabled();
    if (!isEnterprise)
      return (
        <Invisible>{(props as { children?: ReactNode }).children}</Invisible>
      );
    return createElement(EEComponent, props);
  }
  EEGatedWrapper.displayName = `eeGated(${
    EEComponent.displayName || EEComponent.name || "Component"
  })`;
  return EEGatedWrapper;
}
