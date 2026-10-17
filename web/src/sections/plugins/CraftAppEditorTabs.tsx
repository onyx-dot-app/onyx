"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Tabs } from "@opal/components";

interface CraftAppEditorTabsProps {
  value: string;
  onValueChange: (value: string) => void;
  configuration: ReactNode;
  permissions?: ReactNode;
  skills?: ReactNode;
  busy?: boolean;
}

export default function CraftAppEditorTabs({
  value,
  onValueChange,
  configuration,
  permissions,
  skills,
  busy = false,
}: CraftAppEditorTabsProps) {
  const t = useTranslations("actions.plugins.craftApp.tabs");
  const panels = [
    { value: "configuration" as const, content: configuration },
    { value: "permissions" as const, content: permissions },
    { value: "skills" as const, content: skills },
  ].filter((panel) => panel.content !== undefined);

  function pane(content: ReactNode) {
    return (
      <div className="h-[min(24rem,45dvh)] overflow-y-auto">
        <div className="flex flex-col gap-4 pb-1">{content}</div>
      </div>
    );
  }

  if (panels.length === 1) return pane(configuration);

  return (
    <Tabs value={value} onValueChange={onValueChange} gap={6}>
      <Tabs.List>
        {panels.map((panel) => (
          <Tabs.Trigger key={panel.value} value={panel.value} disabled={busy}>
            {t(panel.value)}
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
