import {
  normalizePanelPath,
  panelTabId,
  type PanelTab,
} from "@/app/craft/types/displayTypes";
import type { OutputPanelMode } from "@/lib/outputPanel/layout";
import type { FilesTabState } from "@/app/craft/hooks/useBuildSessionStore";
import {
  clearPanelPreferences,
  readPanelPreferences,
  savePanelPreferences,
} from "@/lib/outputPanel/preferences";

export interface OutputPanelPreferences {
  outputPanelMode: OutputPanelMode;
  outputPanelInitialized: boolean;
  panelTabs: PanelTab[];
  activePanelTabId: string | null;
  panelTabHistory?: string[];
  mediumPanelProportion: number;
  filesTabState?: FilesTabState;
}

const STORAGE_PREFIX = "onyx:craft:output-panel:v1:";

function storageKey(sessionId: string): string {
  return `${STORAGE_PREFIX}${sessionId}`;
}

// oxlint-disable-next-line anti-slop/no-unknown-parameters -- Parses untrusted browser storage at the I/O boundary.
function parseTab(value: unknown): PanelTab | null {
  if (typeof value !== "object" || value === null || !("kind" in value))
    return null;
  if (value.kind === "outputs") return { kind: "outputs" };
  if (value.kind === "files") return { kind: "files" };
  if (
    value.kind === "file" &&
    "path" in value &&
    typeof value.path === "string" &&
    "fileName" in value &&
    typeof value.fileName === "string"
  ) {
    const path = normalizePanelPath(value.path);
    return path ? { kind: "file", path, fileName: value.fileName } : null;
  }
  if (
    value.kind === "browser" &&
    "id" in value &&
    typeof value.id === "string" &&
    value.id.length > 0 &&
    "appId" in value &&
    (value.appId === null || typeof value.appId === "string") &&
    (!("appName" in value) || typeof value.appName === "string")
  ) {
    return {
      kind: "browser",
      id: value.id,
      appId: value.appId,
      ...("appName" in value &&
        typeof value.appName === "string" && { appName: value.appName }),
    };
  }
  return null;
}

export function readOutputPanelPreferences(
  sessionId: string
): OutputPanelPreferences | undefined {
  return readPanelPreferences(storageKey(sessionId), parsePreferences);
}

// oxlint-disable-next-line anti-slop/no-unknown-parameters -- Parses untrusted browser storage at the I/O boundary.
function parsePreferences(value: unknown): OutputPanelPreferences | undefined {
  if (
    typeof value !== "object" ||
    value === null ||
    !("outputPanelMode" in value) ||
    (value.outputPanelMode !== "closed" &&
      value.outputPanelMode !== "medium" &&
      value.outputPanelMode !== "full") ||
    !("outputPanelInitialized" in value) ||
    typeof value.outputPanelInitialized !== "boolean" ||
    !("panelTabs" in value) ||
    !Array.isArray(value.panelTabs) ||
    !("activePanelTabId" in value) ||
    (value.activePanelTabId !== null &&
      typeof value.activePanelTabId !== "string") ||
    !("mediumPanelProportion" in value) ||
    typeof value.mediumPanelProportion !== "number" ||
    !Number.isFinite(value.mediumPanelProportion) ||
    value.mediumPanelProportion <= 0 ||
    value.mediumPanelProportion >= 1
  )
    return undefined;
  const tabs: PanelTab[] = [];
  let filesTabState: FilesTabState | undefined;
  if ("filesTabState" in value && value.filesTabState !== undefined) {
    const files = value.filesTabState;
    if (
      typeof files !== "object" ||
      files === null ||
      !("expandedPaths" in files) ||
      !Array.isArray(files.expandedPaths) ||
      !("scrollTop" in files) ||
      typeof files.scrollTop !== "number" ||
      !Number.isFinite(files.scrollTop) ||
      files.scrollTop < 0
    )
      return undefined;
    const paths: unknown[] = files.expandedPaths;
    const expandedPaths = paths.filter(
      (path): path is string => typeof path === "string"
    );
    if (expandedPaths.length !== paths.length) return undefined;
    filesTabState = {
      expandedPaths: expandedPaths.map(normalizePanelPath).filter(Boolean),
      scrollTop: files.scrollTop,
    };
  }
  const serializedTabs: unknown[] = value.panelTabs;
  for (const item of serializedTabs) {
    const tab = parseTab(item);
    if (
      !tab ||
      tabs.some((existing) => panelTabId(existing) === panelTabId(tab))
    )
      return undefined;
    tabs.push(tab);
  }
  const activePanelTabId = tabs.some(
    (tab) => panelTabId(tab) === value.activePanelTabId
  )
    ? value.activePanelTabId
    : tabs[0]
      ? panelTabId(tabs[0])
      : null;
  return {
    outputPanelMode: value.outputPanelMode,
    outputPanelInitialized: value.outputPanelInitialized,
    panelTabs: tabs,
    activePanelTabId,
    ...("panelTabHistory" in value &&
      Array.isArray(value.panelTabHistory) && {
        panelTabHistory: value.panelTabHistory.filter(
          (id: unknown): id is string => typeof id === "string"
        ),
      }),
    mediumPanelProportion: value.mediumPanelProportion,
    ...(filesTabState && { filesTabState }),
  };
}

export function saveOutputPanelPreferences(
  sessionId: string,
  {
    outputPanelMode,
    outputPanelInitialized,
    panelTabs,
    activePanelTabId,
    panelTabHistory,
    mediumPanelProportion,
    filesTabState,
  }: OutputPanelPreferences
): void {
  savePanelPreferences(storageKey(sessionId), {
    outputPanelMode,
    outputPanelInitialized,
    panelTabs,
    activePanelTabId,
    panelTabHistory,
    mediumPanelProportion,
    filesTabState,
  });
}

export function clearOutputPanelPreferences(sessionId: string): void {
  clearPanelPreferences(storageKey(sessionId));
}
