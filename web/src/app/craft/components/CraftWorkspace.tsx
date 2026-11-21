"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { SvgSidebar } from "@opal/icons";
import { cn } from "@opal/utils";
import {
  useBuildSessionStore,
  useOutputPanelMode,
  useMediumPanelProportion,
  useSessionId,
} from "@/app/craft/hooks/useBuildSessionStore";
import BuildChatPanel from "@/app/craft/components/ChatPanel";
import BuildOutputPanel from "@/app/craft/components/OutputPanel";
import SandboxAsleepNotice from "@/app/craft/components/SandboxAsleepNotice";
import { useOutputPanelPersistence } from "@/lib/build/hooks";
import { OUTPUT_PANEL_HEADER_CONTROL_WIDTH } from "@/lib/outputPanel/layout";
import {
  PanelResizeHandle,
  PanelSizeButton,
  useOutputPanelWorkspace,
} from "@/sections/output-panel/PanelResize";

interface CraftWorkspaceProps {
  existingSessionId: string | null;
}
const PANEL_TRANSITION =
  "transition-[width] duration-180 ease-out motion-reduce:transition-none";

export default function CraftWorkspace({
  existingSessionId,
}: CraftWorkspaceProps) {
  const t = useTranslations("craft.outputWorkspace");
  const mode = useOutputPanelMode();
  const sessionId = useSessionId();
  const proportion = useMediumPanelProportion();
  const setMode = useBuildSessionStore(
    (state) => state.setCurrentOutputPanelMode
  );
  const setProportion = useBuildSessionStore(
    (state) => state.setCurrentMediumPanelProportion
  );
  const workspace = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const chat = useRef<HTMLDivElement>(null);
  const toggleButton = useRef<HTMLElement>(null);
  const [transitionsEnabled, setTransitionsEnabled] = useState(false);
  const open = mode !== "closed";
  const layout = useOutputPanelWorkspace({
    workspaceRef: workspace,
    pageRef: chat,
    coverFocusRef: toggleButton,
    mode,
    proportion,
    onResize: (next) => {
      // A drag that ends after the panel left medium size saves nothing
      if (mode === "medium") setProportion(next);
    },
    onRestore: useCallback(() => setMode("medium"), [setMode]),
    // The width readies the layout before the panel first opens
    measureWhileClosed: true,
    sessionId,
  });
  const layoutReady =
    layout.workspaceWidth > 0 &&
    (existingSessionId === null || sessionId === existingSessionId);
  useEffect(() => {
    if (!layoutReady || transitionsEnabled) return;
    const frame = requestAnimationFrame(() => setTransitionsEnabled(true));
    return () => cancelAnimationFrame(frame);
  }, [layoutReady, transitionsEnabled]);

  useOutputPanelPersistence();

  function toggle() {
    if (open && panel.current?.contains(document.activeElement))
      toggleButton.current?.focus();
    setMode(open ? "closed" : "medium");
  }

  return (
    <div
      ref={workspace}
      className="relative h-full min-w-0 w-full"
      data-output-mode={mode}
    >
      <div
        ref={chat}
        aria-hidden={layout.covers}
        className={cn(
          "h-full overflow-hidden motion-reduce:transition-none",
          transitionsEnabled && !layout.dragging && PANEL_TRANSITION,
          layout.covers && "invisible"
        )}
        style={{
          width: open
            ? layout.narrow
              ? "100%"
              : `${(1 - layout.proportion) * 100}%`
            : "100%",
        }}
      >
        <BuildChatPanel
          existingSessionId={existingSessionId}
          headerControlWidth={open ? 0 : OUTPUT_PANEL_HEADER_CONTROL_WIDTH}
          animateLayout={transitionsEnabled}
        />
      </div>
      <div
        ref={panel}
        inert={!open}
        aria-hidden={!open}
        className={cn(
          "absolute inset-y-0 end-0 isolate overflow-hidden bg-background-neutral-00",
          transitionsEnabled && !layout.dragging && PANEL_TRANSITION,
          !open && "pointer-events-none"
        )}
        style={{
          width: !open
            ? 0
            : mode === "full" || layout.narrow
              ? "100%"
              : `${layout.proportion * 100}%`,
        }}
      >
        <div
          className="absolute inset-y-0 end-0"
          style={{
            width:
              mode === "full" || layout.narrow
                ? layout.workspaceWidth
                : layout.mediumWidth,
          }}
        >
          <BuildOutputPanel
            panelMode={mode}
            headerControlWidth={OUTPUT_PANEL_HEADER_CONTROL_WIDTH}
          />
        </div>
        {/* A narrow workspace always covers the chat: no size to choose */}
        {!layout.narrow && (
          <div
            className={cn(
              "absolute end-9 top-3 flex size-7 items-center justify-center",
              !open && "invisible"
            )}
            inert={!open}
          >
            <PanelSizeButton
              full={mode === "full"}
              expandLabel={t("expand.ariaLabel")}
              restoreLabel={t("restore.ariaLabel")}
              onToggle={() => setMode(mode === "full" ? "medium" : "full")}
            />
          </div>
        )}
        {layout.dragging && (
          <div className="absolute inset-0 z-40 cursor-col-resize" />
        )}
      </div>
      {layout.workspaceWidth > 0 && !layout.narrow && (
        <PanelResizeHandle
          label={t("resize.ariaLabel")}
          workspaceWidth={layout.workspaceWidth}
          mediumWidth={layout.mediumWidth}
          active={mode === "medium"}
          insetInlineEnd={`calc(${!open ? 0 : mode === "full" ? 100 : layout.proportion * 100}% - 8px)`}
          transitions={transitionsEnabled && !layout.dragging}
          handleProps={layout.handleProps}
        />
      )}
      <div className="absolute end-0 top-0 z-40 flex h-[52px] items-center gap-1 pe-3 ps-2">
        <Button
          ref={toggleButton}
          icon={SvgSidebar}
          prominence="tertiary"
          size="sm"
          aria-label={t(open ? "close.ariaLabel" : "open.ariaLabel")}
          tooltip={t(open ? "close.ariaLabel" : "open.ariaLabel")}
          onClick={toggle}
        />
      </div>
      <SandboxAsleepNotice />
    </div>
  );
}
