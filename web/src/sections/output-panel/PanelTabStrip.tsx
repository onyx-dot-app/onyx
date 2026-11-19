"use client";

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useDirection } from "@radix-ui/react-direction";
import { useReducedMotion } from "motion/react";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  horizontalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import {
  restrictToHorizontalAxis,
  restrictToFirstScrollableAncestor,
} from "@dnd-kit/modifiers";
import { CSS } from "@dnd-kit/utilities";
import { useTranslations } from "next-intl";
import {
  Button,
  Dropdown,
  TextButton,
  type DropdownMenuItem,
} from "@opal/components";
import { Hoverable } from "@opal/core";
import { SvgPlus, SvgX } from "@opal/icons";
import type { IconFunctionComponent, RichNodes } from "@opal/types";
import { cn } from "@opal/utils";

export function panelTabDomId(id: string): string {
  return `output-panel-tab-${encodeURIComponent(id)}`;
}
export function panelContentDomId(id: string): string {
  return `output-panel-content-${encodeURIComponent(id)}`;
}

/** One tab of an output panel's tab strip. */
export interface PanelTabItem {
  id: string;
  // The tab's name, also for assistive technology
  label: string;
  // Shown in place of `label` when parts of it need their own direction
  content?: RichNodes;
  icon: IconFunctionComponent;
  // Shows a close button in place of the icon on hover
  closable: boolean;
  // Moves by drag or Alt+arrow, only to the place of another movable tab
  movable: boolean;
}

interface PanelTabStripProps {
  tabs: PanelTabItem[];
  activeTabId: string | null;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  // Moves a movable tab to the index of another movable tab, by drag or
  // Alt+arrow
  onReorder: (id: string, index: number) => void;
  // The "+" menu that opens more tabs
  menuItems?: DropdownMenuItem[];
  // A change closes the "+" menu
  menuResetKey?: string;
  disabled?: boolean;
}
interface SortableTabProps {
  id: string;
  active: boolean;
  disabled: boolean;
  movable: boolean;
  register: (element: HTMLDivElement | null) => void;
  onSelect: () => void;
  children: ReactNode;
}

function SortableTab({
  id,
  active,
  disabled,
  movable,
  register,
  onSelect,
  children,
}: SortableTabProps) {
  const reducedMotion = useReducedMotion();
  const direction = useDirection();
  const { setNodeRef, listeners, transform, transition, isDragging } =
    useSortable({
      id,
      // A boolean only stops dragging; fixed tabs must not take drops either
      disabled: { draggable: disabled || !movable, droppable: !movable },
      transition: reducedMotion ? null : { duration: 180, easing: "ease-out" },
      // Closing a tab shifts its neighbors immediately; only dragging animates them.
      animateLayoutChanges: ({ isSorting }) => isSorting,
    });
  return (
    <Hoverable.Root group="resource-tab" width="fit">
      <div
        role="presentation"
        dir={direction}
        ref={(element) => {
          setNodeRef(element);
          register(element);
        }}
        className={cn(
          "group relative flex h-5.5 w-full max-w-[180px] touch-none select-none items-center gap-1 rounded-md",
          active ? "bg-background-neutral-02" : "bg-background-neutral-01",
          isDragging && "z-10 shadow-md"
        )}
        style={{ transform: CSS.Translate.toString(transform), transition }}
        onClick={() => {
          if (!disabled) onSelect();
        }}
        onPointerDown={(event) => {
          if (
            event.target instanceof Element &&
            event.target.closest("[data-tab-close]")
          )
            return;
          listeners?.onPointerDown?.(event);
        }}
      >
        {children}
      </div>
    </Hoverable.Root>
  );
}

/**
 * The tab strip of an output panel: Craft's workspace panel and the chat's
 * right panel. Tabs can close and reorder, and a "+" menu can open more.
 */
export function PanelTabStrip({
  tabs,
  activeTabId,
  onSelect,
  onClose,
  onReorder,
  menuItems,
  menuResetKey,
  disabled = false,
}: PanelTabStripProps) {
  const t = useTranslations("outputPanel.tabStrip");
  const direction = useDirection();
  const sortableIds = tabs.map((tab) => tab.id);
  // The horizontal strategy expects physical left-to-right order.
  if (direction === "rtl") sortableIds.reverse();
  const strip = useRef<HTMLDivElement>(null);
  const plus = useRef<HTMLElement>(null);
  const nodes = useRef(new Map<string, HTMLDivElement>());
  const suppressClick = useRef(false);
  const closedTab = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (!closedTab.current || tabs.some((tab) => tab.id === closedTab.current))
      return;
    closedTab.current = null;
    if (activeTabId)
      nodes.current
        .get(activeTabId)
        ?.querySelector<HTMLElement>('[role="tab"]')
        ?.focus();
    else plus.current?.focus();
  }, [tabs, activeTabId]);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } })
  );
  const [menu, setMenu] = useState({ mode: menuResetKey, open: false });
  if (menu.mode !== menuResetKey) setMenu({ mode: menuResetKey, open: false });
  const [edges, setEdges] = useState({ start: false, end: false });
  const [announcement, setAnnouncement] = useState("");

  function updateEdges() {
    const element = strip.current;
    if (!element) return;
    const left = element.scrollLeft > 1;
    const right =
      element.scrollLeft + element.clientWidth < element.scrollWidth - 1;
    setEdges(
      direction === "rtl"
        ? { start: right, end: left }
        : { start: left, end: right }
    );
  }
  useEffect(() => {
    const element = strip.current;
    if (!element) return;
    const observer = new ResizeObserver(updateEdges);
    observer.observe(element);
    if (element.firstElementChild) observer.observe(element.firstElementChild);
    updateEdges();
    return () => observer.disconnect();
  }, [direction]);
  useEffect(() => {
    const element = nodes.current.get(activeTabId ?? "");
    const scroller = strip.current;
    if (!element || !scroller) return;
    const bounds = scroller.getBoundingClientRect();
    const tabBounds = element.getBoundingClientRect();
    if (tabBounds.left < bounds.left)
      scroller.scrollLeft += tabBounds.left - bounds.left;
    else if (tabBounds.right > bounds.right)
      scroller.scrollLeft += tabBounds.right - bounds.right;
    updateEdges();
  }, [activeTabId, direction]);
  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      modifiers={[restrictToHorizontalAxis, restrictToFirstScrollableAncestor]}
      autoScroll={{ canScroll: (element) => element === strip.current }}
      accessibility={{
        screenReaderInstructions: { draggable: "" },
        announcements: {
          onDragStart: () => undefined,
          onDragOver: () => undefined,
          onDragEnd: () => undefined,
          onDragCancel: () => undefined,
        },
      }}
      onDragStart={() => {
        suppressClick.current = true;
      }}
      onDragEnd={({ active, over }) => {
        // Fixed tabs take no drops, so `over` is a movable tab or none
        const index = tabs.findIndex((tab) => tab.id === over?.id);
        if (index < 0 || active.id === over?.id) return;
        onReorder(String(active.id), index);
        setAnnouncement(
          t("reordered.label", { position: index + 1, count: tabs.length })
        );
      }}
    >
      <div
        className="flex min-w-0 flex-1 items-center gap-1"
        onPointerDownCapture={() => {
          suppressClick.current = false;
        }}
        onClickCapture={(event) => {
          if (!suppressClick.current || event.detail === 0) return;
          event.preventDefault();
          event.stopPropagation();
        }}
      >
        <div className="relative min-w-0">
          {/* Keep scrollLeft nonnegative for dnd-kit; the inner row preserves UI direction. */}
          <div
            ref={strip}
            dir="ltr"
            role="tablist"
            aria-label={t("list.label")}
            className="min-w-0 overflow-x-auto overscroll-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
            onScroll={updateEdges}
            onWheel={(event) => {
              if (
                Math.abs(event.deltaY) > Math.abs(event.deltaX) &&
                strip.current &&
                strip.current.scrollWidth > strip.current.clientWidth
              ) {
                event.preventDefault();
                strip.current.scrollLeft +=
                  event.deltaY * (direction === "rtl" ? -1 : 1);
              }
            }}
          >
            {/* Tabs shrink to a minimum before the strip scrolls */}
            <div
              dir={direction}
              className="flex min-w-full items-center gap-1 [&>*]:min-w-16 [&>*]:shrink"
            >
              <SortableContext
                items={sortableIds}
                strategy={horizontalListSortingStrategy}
              >
                {tabs.map((tab, index) => {
                  const id = tab.id;
                  const active = id === activeTabId;
                  const Icon = tab.icon;
                  const iconTile = (
                    <div
                      className="flex size-5 items-center justify-center text-text-03"
                      aria-hidden
                    >
                      <Icon className="size-3" />
                    </div>
                  );
                  return (
                    <SortableTab
                      key={id}
                      id={id}
                      active={active}
                      disabled={disabled}
                      movable={tab.movable}
                      onSelect={() => onSelect(id)}
                      register={(element) => {
                        if (element) nodes.current.set(id, element);
                        else nodes.current.delete(id);
                      }}
                    >
                      <div className="flex size-5 shrink-0 items-center justify-center">
                        {tab.closable ? (
                          <Hoverable.Item
                            group="resource-tab"
                            variant="replace-on-hover"
                            resting={iconTile}
                          >
                            <Button
                              data-tab-close
                              disabled={disabled}
                              icon={SvgX}
                              size="2xs"
                              prominence="tertiary"
                              aria-label={t("close.label", { name: tab.label })}
                              onClick={(event) => {
                                event.stopPropagation();
                                closedTab.current = id;
                                onClose(id);
                              }}
                            />
                          </Hoverable.Item>
                        ) : (
                          iconTile
                        )}
                      </div>
                      <div className="min-w-0 overflow-hidden pe-2 [&_p]:truncate">
                        <TextButton
                          passive
                          disabled={disabled}
                          role="tab"
                          id={panelTabDomId(id)}
                          aria-controls={panelContentDomId(id)}
                          aria-selected={active}
                          aria-label={tab.label}
                          // Labels can be names that the model or sandbox chose
                          dir="auto"
                          tabIndex={
                            active || (!activeTabId && index === 0) ? 0 : -1
                          }
                          font="secondary-body"
                          onKeyDown={(event) => {
                            if (disabled) return;
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              onSelect(id);
                              return;
                            }
                            const rtl = direction === "rtl";
                            const delta =
                              event.key === "ArrowLeft"
                                ? rtl
                                  ? 1
                                  : -1
                                : event.key === "ArrowRight"
                                  ? rtl
                                    ? -1
                                    : 1
                                  : 0;
                            if (event.altKey && delta) {
                              event.preventDefault();
                              const destination = index + delta;
                              if (!tab.movable || !tabs[destination]?.movable)
                                return;
                              onReorder(id, destination);
                              setAnnouncement(
                                t("reordered.label", {
                                  position: destination + 1,
                                  count: tabs.length,
                                })
                              );
                              return;
                            }
                            const destination =
                              event.key === "Home"
                                ? 0
                                : event.key === "End"
                                  ? tabs.length - 1
                                  : delta
                                    ? (index + delta + tabs.length) %
                                      tabs.length
                                    : -1;
                            const next = tabs[destination];
                            if (next) {
                              event.preventDefault();
                              onSelect(next.id);
                              nodes.current
                                .get(next.id)
                                ?.querySelector<HTMLElement>('[role="tab"]')
                                ?.focus();
                            }
                          }}
                        >
                          {tab.content ?? tab.label}
                        </TextButton>
                      </div>
                    </SortableTab>
                  );
                })}
              </SortableContext>
            </div>
          </div>
          {edges.start && (
            <div
              aria-hidden
              className="pointer-events-none absolute inset-y-0 start-0 w-5 bg-gradient-to-r from-background-neutral-01 to-transparent rtl:bg-gradient-to-l"
            />
          )}
          {edges.end && (
            <div
              aria-hidden
              className="pointer-events-none absolute inset-y-0 end-0 w-5 bg-gradient-to-l from-background-neutral-01 to-transparent rtl:bg-gradient-to-r"
            />
          )}
        </div>
        {menuItems && (
          <Dropdown
            open={menu.open}
            onOpenChange={(open) => setMenu({ mode: menuResetKey, open })}
            width={40}
            disabled={disabled}
          >
            <Dropdown.Trigger asChild>
              <Button
                ref={plus}
                icon={SvgPlus}
                size="sm"
                prominence="tertiary"
                aria-label={t("open.label")}
              />
            </Dropdown.Trigger>
            <Dropdown.Data
              sizePreset="secondary"
              label={t("open.label")}
              items={menuItems}
            />
          </Dropdown>
        )}
        <div className="sr-only" role="status" aria-live="polite">
          {announcement}
        </div>
      </div>
    </DndContext>
  );
}
