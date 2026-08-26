"use client";

import {
  memo,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { useTranslations } from "next-intl";
import { Popover, Text } from "@opal/components";
import LineItem from "@/refresh-components/buttons/LineItem";
import {
  filterPickerSections,
  flattenSections,
  pickerEntryKey,
  type PickerEntry,
  type PickerSections,
} from "@/lib/skills/picker";
import { pickerEntryIcon } from "@/lib/skills/pickerIcons";
import { cn } from "@opal/utils";
import type { IconFunctionComponent } from "@opal/types";

interface EntryPickerPopoverProps {
  open: boolean;
  anchorRect: DOMRect | null;
  query: string;
  sections: PickerSections;
  onSelect: (entry: PickerEntry) => void;
  onClose: () => void;
}

function EntryPickerPopover({
  open,
  anchorRect,
  query,
  sections,
  onSelect,
  onClose,
}: EntryPickerPopoverProps) {
  const t = useTranslations("chat.input");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(
    () => filterPickerSections(sections, query),
    [sections, query]
  );
  const flatEntries = useMemo(() => flattenSections(filtered), [filtered]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [open, query]);

  // SWR may revalidate while open and shrink the row count; clamp so Enter
  // doesn't silently fall back to a different row than the one highlighted.
  useEffect(() => {
    setSelectedIndex((i) =>
      flatEntries.length === 0 ? 0 : Math.min(i, flatEntries.length - 1)
    );
  }, [flatEntries.length]);

  useEffect(() => {
    if (!open) return;
    const container = scrollContainerRef.current;
    if (!container) return;
    const row = container.querySelector<HTMLElement>(
      `[data-row-index="${selectedIndex}"]`
    );
    row?.scrollIntoView({ block: "nearest" });
  }, [open, selectedIndex]);

  useEffect(() => {
    if (!open) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        e.stopPropagation();
        if (flatEntries.length === 0) return;
        setSelectedIndex((i) => (i + 1) % flatEntries.length);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        e.stopPropagation();
        if (flatEntries.length === 0) return;
        setSelectedIndex(
          (i) => (i - 1 + flatEntries.length) % flatEntries.length
        );
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        e.stopPropagation();
        if (flatEntries.length === 0) {
          onClose();
          return;
        }
        const entry = flatEntries[selectedIndex] ?? flatEntries[0];
        if (entry) onSelect(entry);
      } else if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    }

    document.addEventListener("keydown", handleKeyDown, true);
    return () => document.removeEventListener("keydown", handleKeyDown, true);
  }, [open, flatEntries, selectedIndex, onSelect, onClose]);

  if (!anchorRect) return null;

  // `position: fixed` is containing-block-relative under a transformed
  // ancestor (Storybook docs view, some app shells), so portal to body to
  // keep the anchor's coords viewport-relative.
  if (typeof document === "undefined") return null;

  return createPortal(
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <Popover.Anchor asChild>
        <div
          aria-hidden
          style={{
            position: "fixed",
            left: anchorRect.left,
            top: anchorRect.top,
            width: 0,
            height: anchorRect.height || 1,
            pointerEvents: "none",
          }}
        />
      </Popover.Anchor>
      <Popover.Content
        side="top"
        align="start"
        width="xl"
        onOpenAutoFocus={(e) => e.preventDefault()}
        data-testid="skill-picker-popover"
        aria-label={t("entryPickerPopover.content.ariaLabel")}
      >
        <Popover.Menu scrollContainerRef={scrollContainerRef}>
          {buildMenuChildren({
            filtered,
            flatEntries,
            selectedIndex,
            onSelect,
            onHover: setSelectedIndex,
            emptyMessage: t("entryPickerPopover.empty.text"),
            groupLabels: {
              skills: t("entryPickerPopover.skillsGroup.label"),
              apps: t("entryPickerPopover.appsGroup.label"),
              mcpServers: t("entryPickerPopover.mcpServersGroup.label"),
            },
          })}
        </Popover.Menu>
      </Popover.Content>
    </Popover>,
    document.body
  );
}

interface BuildMenuChildrenArgs {
  filtered: PickerSections;
  flatEntries: PickerEntry[];
  selectedIndex: number;
  onSelect: (entry: PickerEntry) => void;
  onHover: (idx: number) => void;
  /** Translated copy: this helper is not a component, so it cannot call `t`. */
  emptyMessage: string;
  groupLabels: { skills: string; apps: string; mcpServers: string };
}

// `Popover.Menu` renders a literal `null` between children as a divider.
function buildMenuChildren({
  filtered,
  flatEntries,
  selectedIndex,
  onSelect,
  onHover,
  emptyMessage,
  groupLabels,
}: BuildMenuChildrenArgs): ReactNode[] {
  if (flatEntries.length === 0) {
    return [
      <div key="empty" className="p-2">
        <Text font="secondary-body" color="text-03">
          {emptyMessage}
        </Text>
      </div>,
    ];
  }

  // Groups must stay in `flattenSections` order — keyboard nav indexes into that
  // flat list, so a running index is what keeps the two aligned.
  const groups: { key: string; label: string; entries: PickerEntry[] }[] = [
    { key: "skills", label: groupLabels.skills, entries: filtered.skills },
    { key: "apps", label: groupLabels.apps, entries: filtered.apps },
    {
      key: "mcpServers",
      label: groupLabels.mcpServers,
      entries: filtered.mcpServers,
    },
  ];

  const children: ReactNode[] = [];
  let idx = 0;

  for (const group of groups) {
    if (group.entries.length === 0) continue;
    if (children.length > 0) children.push(null);
    children.push(
      <SectionHeader key={`${group.key}-header`} label={group.label} />
    );
    for (const entry of group.entries) {
      const rowProps = {
        key: pickerEntryKey(entry),
        selected: idx === selectedIndex,
        onHover: () => onHover(idx),
        onPick: () => onSelect(entry),
        rowIndex: idx,
      };
      children.push(
        entry.kind === "skill" ? (
          <SkillRow
            {...rowProps}
            slug={entry.slug}
            description={entry.description}
          />
        ) : (
          <ConnectableRow
            {...rowProps}
            logo={pickerEntryIcon(entry)}
            name={entry.name}
            authenticated={entry.authenticated}
            testId={
              entry.kind === "app"
                ? `app-picker-row-${entry.externalAppId}`
                : `mcp-picker-row-${entry.mcpServerId}`
            }
          />
        )
      );
      idx += 1;
    }
  }

  return children;
}

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="px-2 pt-1 pb-0.5">
      <Text font="secondary-action" color="text-03">
        {label}
      </Text>
    </div>
  );
}

interface SkillRowProps {
  slug: string;
  description: string;
  selected: boolean;
  onHover: () => void;
  onPick: () => void;
  rowIndex: number;
}

function SkillRow({
  slug,
  description,
  selected,
  onHover,
  onPick,
  rowIndex,
}: SkillRowProps) {
  return (
    <div className="cursor-pointer">
      <LineItem
        interactive={false}
        selected={selected}
        emphasized={selected}
        description={description}
        onMouseEnter={onHover}
        onMouseDown={(e) => {
          e.preventDefault();
          onPick();
        }}
        data-row-index={rowIndex}
        data-testid={`skill-picker-row-${slug}`}
      >
        {`/${slug}`}
      </LineItem>
    </div>
  );
}

interface ConnectableRowProps {
  logo: IconFunctionComponent;
  name: string;
  authenticated: boolean;
  testId: string;
  selected: boolean;
  onHover: () => void;
  onPick: () => void;
  rowIndex: number;
}

// Shared by external apps and MCP servers: identical affordances, and the
// section header above already says which kind the row is.
function ConnectableRow({
  logo: Logo,
  name,
  authenticated,
  testId,
  selected,
  onHover,
  onPick,
  rowIndex,
}: ConnectableRowProps) {
  const t = useTranslations("chat.input");
  const unauth = !authenticated;
  return (
    <div className="cursor-pointer">
      <LineItem
        interactive={false}
        selected={selected}
        emphasized={selected}
        description={
          authenticated
            ? t("entryPickerPopover.connectedRow.description")
            : t("entryPickerPopover.connectionRequiredRow.description")
        }
        onMouseEnter={onHover}
        onMouseDown={(e) => {
          e.preventDefault();
          onPick();
        }}
        rightChildren={
          unauth ? (
            <Text font="secondary-action" color="text-03" nowrap>
              {t("entryPickerPopover.connectAction.label")}
            </Text>
          ) : undefined
        }
        data-row-index={rowIndex}
        data-testid={testId}
      >
        <span
          className={cn(
            "inline-flex items-center gap-2",
            unauth && "opacity-50"
          )}
        >
          <Logo className="h-4 w-4 shrink-0" />
          <span>{name}</span>
        </span>
      </LineItem>
    </div>
  );
}

export default memo(EntryPickerPopover);
