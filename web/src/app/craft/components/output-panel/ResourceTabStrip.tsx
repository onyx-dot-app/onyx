"use client";

import { useTranslations } from "next-intl";
import { SvgFile, SvgFiles, SvgFolder, SvgGlobe } from "@opal/icons";
import { panelTabId, type PanelTab } from "@/app/craft/types/displayTypes";
import type { OutputPanelMode } from "@/lib/outputPanel/layout";
import { PanelTabStrip } from "@/sections/output-panel/PanelTabStrip";

interface ResourceTabStripProps {
  tabs: PanelTab[];
  activeTabId: string | null;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  onReorder: (id: string, index: number) => void;
  onOpenOutputs: () => void;
  onOpenFiles: () => void;
  onOpenBrowser: () => void;
  panelMode?: OutputPanelMode;
  disabled?: boolean;
}

/** Craft's workspace tabs: outputs, files, file previews and browsers. */
export default function ResourceTabStrip({
  tabs,
  onOpenOutputs,
  onOpenFiles,
  onOpenBrowser,
  panelMode,
  ...strip
}: ResourceTabStripProps) {
  const t = useTranslations("craft.resourceTabs");
  return (
    <PanelTabStrip
      {...strip}
      menuResetKey={panelMode}
      tabs={tabs.map((tab) => ({
        id: panelTabId(tab),
        closable: true,
        movable: true,
        label:
          tab.kind === "outputs"
            ? t("outputs.label")
            : tab.kind === "files"
              ? t("files.label")
              : tab.kind === "file"
                ? tab.fileName
                : (tab.appName ?? t("browser.label")),
        icon:
          tab.kind === "outputs"
            ? SvgFiles
            : tab.kind === "files"
              ? SvgFolder
              : tab.kind === "browser"
                ? SvgGlobe
                : SvgFile,
      }))}
      menuItems={[
        {
          kind: "action",
          id: "outputs",
          title: t("outputs.label"),
          icon: SvgFiles,
          onSelect: onOpenOutputs,
        },
        {
          kind: "action",
          id: "files",
          title: t("files.label"),
          icon: SvgFolder,
          onSelect: onOpenFiles,
        },
        {
          kind: "action",
          id: "browser",
          title: t("browser.label"),
          icon: SvgGlobe,
          onSelect: onOpenBrowser,
        },
      ]}
    />
  );
}
