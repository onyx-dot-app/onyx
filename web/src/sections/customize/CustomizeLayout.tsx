"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { InputTypeIn } from "@opal/components";
import { Section, SettingsLayouts } from "@opal/layouts";
import type { CustomizeTab } from "@/lib/customize/paths";

interface CustomizeLayoutProps {
  tab: CustomizeTab;
  query: string;
  onQueryChange: (query: string) => void;
  controls: ReactNode;
  loading?: boolean;
  error?: string | false;
  children: ReactNode;
}

export default function CustomizeLayout({
  tab,
  query,
  onQueryChange,
  controls,
  loading = false,
  error = false,
  children,
}: CustomizeLayoutProps) {
  const t = useTranslations("customize");
  return (
    <SettingsLayouts.Root width="lg" loading={loading} error={error}>
      <SettingsLayouts.Header title={t(`tabs.${tab}`)}>
        <Section
          flexDirection="row"
          justifyContent="end"
          alignItems="center"
          width="auto"
          height="auto"
          gap={0.5}
          grow={1}
        >
          <Section height="auto" basis={16}>
            <InputTypeIn
              icon="search"
              value={query}
              placeholder={t("search")}
              aria-label={t("search")}
              onChange={(event) => onQueryChange(event.target.value)}
            />
          </Section>
          {controls}
        </Section>
      </SettingsLayouts.Header>
      <SettingsLayouts.Body>{children}</SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
