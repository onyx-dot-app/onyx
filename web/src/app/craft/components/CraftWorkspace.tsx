"use client";

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent,
  type KeyboardEvent,
} from "react";
import { useTranslations } from "next-intl";
import { useDirection } from "@radix-ui/react-direction";
import { Button } from "@opal/components";
import { SvgSidebar, SvgMaximize2, SvgFold } from "@opal/icons";
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

interface CraftWorkspaceProps {
  existingSessionId: string | null;
}
interface WorkspaceResize {
  sessionId: string | null;
  pointerId: number;
  proportion: number;
  frame: number | null;
}
const MIN_CHAT_WIDTH = 400;
const MIN_OUTPUT_WIDTH = 280;
const PANEL_TRANSITION =
  "transition-[width] duration-180 ease-out motion-reduce:transition-none";

export default function CraftWorkspace({
  existingSessionId,
}: CraftWorkspaceProps) {
  const t = useTranslations("craft.outputWorkspace");
  const direction = useDirection();
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
  const controls = useRef<HTMLDivElement>(null);
  const [workspaceWidth, setWorkspaceWidth] = useState(0);
  const resizeGesture = useRef<WorkspaceResize | null>(null);
  const [previewProportion, setPreviewProportion] = useState<number | null>(
    null
  );
  const dragging = previewProportion !== null;
  const [transitionsEnabled, setTransitionsEnabled] = useState(false);
  const layoutReady =
    workspaceWidth > 0 &&
    (existingSessionId === null || sessionId === existingSessionId);
  useEffect(() => {
    if (!layoutReady || transitionsEnabled) return;
    const frame = requestAnimationFrame(() => setTransitionsEnabled(true));
    return () => cancelAnimationFrame(frame);
  }, [layoutReady, transitionsEnabled]);
  const headerControlWidth = 76;
  const open = mode !== "closed";
  const narrow =
    workspaceWidth > 0 && workspaceWidth < MIN_CHAT_WIDTH + MIN_OUTPUT_WIDTH;
  const minimumProportion =
    workspaceWidth > 0 ? MIN_OUTPUT_WIDTH / workspaceWidth : 0.5;
  const maximumProportion =
    workspaceWidth > 0 ? 1 - MIN_CHAT_WIDTH / workspaceWidth : 0.5;
  const boundedProportion = narrow
    ? 0.5
    : Math.max(
        minimumProportion,
        Math.min(maximumProportion, previewProportion ?? proportion)
      );
  const mediumWidth = workspaceWidth * boundedProportion;
  const coversChat = open && (mode === "full" || narrow);

  useLayoutEffect(() => {
    const element = chat.current;
    if (!element) return;
    if (coversChat && element.contains(document.activeElement)) {
      controls.current
        ?.querySelector<HTMLButtonElement>("[data-output-toggle]")
        ?.focus();
    }
    element.inert = coversChat;
  }, [coversChat]);

  useOutputPanelPersistence();

  useEffect(() => {
    const element = workspace.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWorkspaceWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    function restore(event: globalThis.KeyboardEvent) {
      const state = useBuildSessionStore.getState();
      const currentMode = state.currentSessionId
        ? state.sessions.get(state.currentSessionId)?.outputPanelMode
        : state.noSessionOutputPanelMode;
      if (
        event.key !== "Escape" ||
        event.defaultPrevented ||
        currentMode !== "full"
      )
        return;
      if (
        document.querySelector(
          '[role="dialog"], [role="menu"], [data-state="open"][role="listbox"]'
        )
      )
        return;
      event.preventDefault();
      setMode("medium");
    }
    window.addEventListener("keydown", restore);
    return () => window.removeEventListener("keydown", restore);
  }, [setMode]);

  useEffect(() => {
    if (!dragging) return;
    const previous = document.body.style.userSelect;
    document.body.style.userSelect = "none";
    return () => {
      document.body.style.userSelect = previous;
    };
  }, [dragging]);

  useEffect(
    () => () => {
      const gesture = resizeGesture.current;
      resizeGesture.current = null;
      if (gesture?.frame != null) cancelAnimationFrame(gesture.frame);
    },
    []
  );

  useEffect(() => {
    const gesture = resizeGesture.current;
    if (!gesture) return;
    resizeGesture.current = null;
    if (gesture.frame !== null) cancelAnimationFrame(gesture.frame);
    setPreviewProportion(null);
  }, [sessionId, mode, narrow]);

  function toggle() {
    if (open && panel.current?.contains(document.activeElement)) {
      controls.current
        ?.querySelector<HTMLButtonElement>("[data-output-toggle]")
        ?.focus();
    }
    setMode(open ? "closed" : "medium");
  }

  function resizeAt(clientX: number) {
    const gesture = resizeGesture.current;
    if (!gesture) return;
    const bounds = workspace.current?.getBoundingClientRect();
    if (!bounds || !bounds.width) return;
    const width =
      direction === "rtl" ? clientX - bounds.left : bounds.right - clientX;
    gesture.proportion =
      Math.max(
        MIN_OUTPUT_WIDTH,
        Math.min(bounds.width - MIN_CHAT_WIDTH, width)
      ) / bounds.width;
    if (gesture.frame === null) {
      gesture.frame = requestAnimationFrame(() => {
        gesture.frame = null;
        if (resizeGesture.current === gesture)
          setPreviewProportion(gesture.proportion);
      });
    }
  }

  function finishDrag(event: PointerEvent<HTMLDivElement>, cancelled = false) {
    const gesture = resizeGesture.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    if (!cancelled) resizeAt(event.clientX);
    resizeGesture.current = null;
    if (gesture.frame !== null) cancelAnimationFrame(gesture.frame);
    const state = useBuildSessionStore.getState();
    const currentMode = state.currentSessionId
      ? state.sessions.get(state.currentSessionId)?.outputPanelMode
      : state.noSessionOutputPanelMode;
    if (
      !cancelled &&
      currentMode === "medium" &&
      state.currentSessionId === gesture.sessionId
    )
      setProportion(gesture.proportion);
    setPreviewProportion(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function resizeWithKeyboard(event: KeyboardEvent<HTMLDivElement>) {
    if (!workspaceWidth) return;
    const step = event.shiftKey ? 80 : 20;
    let nextWidth = mediumWidth;
    if (event.key === "Home") nextWidth = MIN_OUTPUT_WIDTH;
    else if (event.key === "End") nextWidth = workspaceWidth - MIN_CHAT_WIDTH;
    else if (event.key === "ArrowLeft")
      nextWidth += direction === "rtl" ? -step : step;
    else if (event.key === "ArrowRight")
      nextWidth += direction === "rtl" ? step : -step;
    else return;
    event.preventDefault();
    setProportion(
      Math.max(
        MIN_OUTPUT_WIDTH,
        Math.min(workspaceWidth - MIN_CHAT_WIDTH, nextWidth)
      ) / workspaceWidth
    );
  }

  return (
    <div
      ref={workspace}
      className="relative h-full min-w-0 w-full"
      data-output-mode={mode}
    >
      <div
        ref={chat}
        aria-hidden={coversChat}
        className={cn(
          "h-full overflow-hidden motion-reduce:transition-none",
          transitionsEnabled && !dragging && PANEL_TRANSITION,
          coversChat && "invisible"
        )}
        style={{
          width: open
            ? narrow
              ? "100%"
              : `${(1 - boundedProportion) * 100}%`
            : "100%",
        }}
      >
        <BuildChatPanel
          existingSessionId={existingSessionId}
          headerControlWidth={open ? 0 : headerControlWidth}
          animateLayout={transitionsEnabled}
        />
      </div>
      <div
        ref={panel}
        inert={!open}
        aria-hidden={!open}
        className={cn(
          "absolute inset-y-0 end-0 isolate overflow-hidden bg-background-neutral-00",
          transitionsEnabled && !dragging && PANEL_TRANSITION,
          !open && "pointer-events-none"
        )}
        style={{
          width: !open
            ? 0
            : mode === "full" || narrow
              ? "100%"
              : `${boundedProportion * 100}%`,
        }}
      >
        <div
          className="absolute inset-y-0 end-0"
          style={{
            width: mode === "full" || narrow ? workspaceWidth : mediumWidth,
          }}
        >
          <BuildOutputPanel
            panelMode={mode}
            headerControlWidth={headerControlWidth}
          />
        </div>
        <div
          className={cn(
            "absolute end-9 top-3 flex size-7 items-center justify-center",
            !open && "invisible"
          )}
          inert={!open}
        >
          <Button
            icon={mode === "full" ? SvgFold : SvgMaximize2}
            prominence="tertiary"
            size="sm"
            aria-label={t(
              mode === "full" ? "restore.ariaLabel" : "expand.ariaLabel"
            )}
            tooltip={t(
              mode === "full" ? "restore.ariaLabel" : "expand.ariaLabel"
            )}
            onClick={() => setMode(mode === "full" ? "medium" : "full")}
          />
        </div>
        {dragging && (
          <div className="absolute inset-0 z-40 cursor-col-resize" />
        )}
      </div>
      {workspaceWidth > 0 && !narrow && (
        <div
          role="separator"
          tabIndex={mode === "medium" ? 0 : -1}
          inert={mode !== "medium"}
          aria-hidden={mode !== "medium"}
          aria-label={t("resize.ariaLabel")}
          aria-orientation="vertical"
          aria-valuemin={MIN_OUTPUT_WIDTH}
          aria-valuemax={Math.max(
            MIN_OUTPUT_WIDTH,
            workspaceWidth - MIN_CHAT_WIDTH
          )}
          aria-valuenow={Math.round(mediumWidth)}
          className={cn(
            "absolute inset-y-0 z-30 w-2 cursor-col-resize touch-none hover:bg-background-tint-02 focus-visible:bg-background-tint-02 focus-visible:outline focus-visible:outline-1 focus-visible:outline-border-03",
            transitionsEnabled &&
              !dragging &&
              "transition-[inset-inline-end] duration-180 ease-out motion-reduce:transition-none",
            mode !== "medium" && "invisible pointer-events-none"
          )}
          style={{
            insetInlineEnd: `calc(${!open ? 0 : mode === "full" ? 100 : boundedProportion * 100}% - 8px)`,
          }}
          onPointerDown={(event) => {
            if (event.button !== 0 || resizeGesture.current) return;
            event.preventDefault();
            event.currentTarget.setPointerCapture(event.pointerId);
            resizeGesture.current = {
              sessionId,
              pointerId: event.pointerId,
              proportion: boundedProportion,
              frame: null,
            };
            setPreviewProportion(boundedProportion);
          }}
          onPointerMove={(event) => {
            if (resizeGesture.current?.pointerId === event.pointerId)
              resizeAt(event.clientX);
          }}
          onPointerUp={finishDrag}
          onPointerCancel={(event) => finishDrag(event, true)}
          onLostPointerCapture={(event) => finishDrag(event, true)}
          onDoubleClick={() => setProportion(0.5)}
          onKeyDown={resizeWithKeyboard}
        />
      )}
      <div
        ref={controls}
        className="absolute end-0 top-0 z-40 flex h-[52px] items-center gap-1 pe-3 ps-2"
      >
        <Button
          data-output-toggle
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
