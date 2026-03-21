"use client";

import { ReactNode } from "react";

import Text from "@/refresh-components/texts/Text";

interface AuthPanelIntroProps {
  children: ReactNode;
  description: string;
  eyebrow: string;
}

export default function AuthPanelIntro({
  children,
  description,
  eyebrow,
}: AuthPanelIntroProps) {
  return (
    <div className="flex w-full flex-col border-b border-border-01 pb-6">
      <Text
        as="p"
        className="text-[11px] font-semibold uppercase tracking-[0.18em] text-theme-orange-05"
      >
        {eyebrow}
      </Text>
      <Text as="p" headingH2 className="pt-3 text-text-05">
        {children}
      </Text>
      <Text as="p" mainUiMuted className="pt-2 text-text-03">
        {description}
      </Text>
    </div>
  );
}
