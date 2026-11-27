"use client";

import { useTranslations } from "next-intl";
import { SettingsLayouts } from "@opal/layouts";
import { SvgSliders } from "@opal/icons";

interface LayoutProps {
  children: React.ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const t = useTranslations("settings.layout");
  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={SvgSliders}
        title={t("header.title")}
        divider
      />
      <SettingsLayouts.Body>{children}</SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
