"use client";

import { Logo } from "@/lib/app/components";

export function renderAppLogo(folded: boolean | undefined): React.ReactNode {
  return <Logo folded={folded} size={28} />;
}
