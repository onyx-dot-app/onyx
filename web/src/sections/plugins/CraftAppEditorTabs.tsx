"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Tabs } from "@opal/components";

interface CraftAppEditorTabsProps {
  value: string;
  onValueChange: (value: string) => void;
  configuration: ReactNode;
  authentication?: ReactNode;
  tools?: ReactNode;
  skills?: ReactNode;
  busy?: boolean;
}

export default function CraftAppEditorTabs({
  value,
  onValueChange,
  configuration,
  authentication,
  tools,
  skills,
  busy = false,
}: CraftAppEditorTabsProps) {
  const t = useTranslations("actions");
  const panels = [
    {
      value: "configuration" as const,
      label: t("plugins.craftApp.tabs.configuration"),
      content: configuration,
    },
    {
      value: "authentication" as const,
      label: t("mcpDetail.authentication"),
      content: authentication,
    },
    { value: "tools" as const, label: t("mcpTools.title"), content: tools },
    {
      value: "skills" as const,
      label: t("plugins.craftApp.tabs.skills"),
      content: skills,
    },
  ].filter((panel) => panel.content !== undefined);

  function pane(content: ReactNode) {
    return <div className="flex flex-col gap-4 pb-1">{content}</div>;
  }

  if (panels.length === 1) return pane(configuration);

  return (
    <Tabs value={value} onValueChange={onValueChange} gap={6}>
      <Tabs.List>
        {panels.map((panel) => (
          <Tabs.Trigger key={panel.value} value={panel.value} disabled={busy}>
            {panel.label}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
      {panels.map((panel) => (
        <Tabs.Content
          key={panel.value}
          value={panel.value}
          keepMounted
          hidden={value !== panel.value}
        >
          {pane(panel.content)}
        </Tabs.Content>
      ))}
    </Tabs>
  );
}
