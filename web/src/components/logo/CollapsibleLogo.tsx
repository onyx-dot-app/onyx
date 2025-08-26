"use client";

import React from "react";
import { Logo } from "@/components/logo/Logo";
import { LogoComponent } from "@/components/logo/FixedLogo";

export default function CollapsibleLogo(
  props: React.ComponentProps<typeof LogoComponent>
) {
  return (
    <>
      <div className="block mobile:hidden">
        <LogoComponent {...props} />
      </div>
      <Logo className="block desktop:hidden" size="small" {...props} />
    </>
  );
}
