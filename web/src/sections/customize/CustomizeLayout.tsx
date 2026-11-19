"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { InputTypeIn, Tabs } from "@opal/components";
import { Section, SettingsLayouts } from "@opal/layouts";
import { useNavigation, usePathname } from "@opal/navigation";
import {
  CUSTOMIZE_TABS as TABS,
  customizeTabHref,
  type CustomizeTab,
} from "@/lib/customize/paths";

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
  const navigation = useNavigation();
  const pathname = usePathname();
  const shown =
    TABS.find((candidate) => pathname === customizeTabHref(candidate)) ?? tab;
  return (
    <SettingsLayouts.Root width="lg" loading={loading} error={error}>
      <SettingsLayouts.Header title={t("title")}>
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="end"
          height="auto"
          gap={1}
          wrap
        >
          <Section width="auto" height="auto">
            <Tabs
              value={shown}
              variant="pill"
              onValueChange={(value) => {
                const next = TABS.find((candidate) => candidate === value);
                if (next)
                  navigation.go(customizeTabHref(next), { scroll: false });
              }}
            >
              <Tabs.List aria-label={t("tabs.label")}>
                {TABS.map((value) => (
                  <Tabs.Trigger key={value} value={value}>
                    {t(`tabs.${value}`)}
                  </Tabs.Trigger>
                ))}
              </Tabs.List>
            </Tabs>
          </Section>
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
        </Section>
      </SettingsLayouts.Header>
      <SettingsLayouts.Body>{children}</SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
