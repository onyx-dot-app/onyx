"use client";

import { Logo } from "@/lib/app/components";
import { IconFunctionComponent } from "@opal/types";

export function renderAppLogo(
  folded: boolean | undefined
): IconFunctionComponent {
  return (props) => <Logo {...props} folded={folded} />;
}
