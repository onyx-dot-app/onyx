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
import { Popover, Text } from "@opal/components";
import LineItem from "@/refresh-components/buttons/LineItem";
import {
  filterPickerSections,
  flattenSections,
  type PickerApp,
  type PickerEntry,
  type PickerSections,
} from "@/lib/skills/picker";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";
import { cn } from "@opal/utils";

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
        aria-label="Skill picker"
      >
        <Popover.Menu scrollContainerRef={scrollContainerRef}>
          {buildMenuChildren({
            filtered,
            flatEntries,
            selectedIndex,
            onSelect,
            onHover: setSelectedIndex,
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
}

// `Popover.Menu` renders a literal `null` between children as a divider.
function buildMenuChildren({
  filtered,
  flatEntries,
  selectedIndex,
  onSelect,
  onHover,
}: BuildMenuChildrenArgs): ReactNode[] {
  if (flatEntries.length === 0) {
    return [
      <div key="empty" className="p-2">
        <Text font="secondary-body" color="text-03">
          No matching skills
        </Text>
      </div>,
    ];
  }

  const skillsCount = filtered.skills.length;
  const children: ReactNode[] = [];

  flatEntries.forEach((entry, idx) => {
    if (idx === 0 && skillsCount > 0) {
      children.push(<SectionHeader key="skills-header" label="Skills" />);
    }
    if (idx === skillsCount && filtered.apps.length > 0) {
      if (skillsCount > 0) children.push(null);
      children.push(<SectionHeader key="apps-header" label="Apps" />);
    }
    const selected = idx === selectedIndex;
    children.push(
      entry.kind === "app" ? (
        <AppRow
          key={`app-${entry.slug}`}
          app={entry}
          selected={selected}
          onHover={() => onHover(idx)}
          onPick={() => onSelect(entry)}
          rowIndex={idx}
        />
      ) : (
        <SkillRow
          key={`skill-${entry.slug}`}
          slug={entry.slug}
          description={entry.description}
          selected={selected}
          onHover={() => onHover(idx)}
          onPick={() => onSelect(entry)}
          rowIndex={idx}
        />
      )
    );
  });

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

interface AppRowProps {
  app: PickerApp;
  selected: boolean;
  onHover: () => void;
  onPick: () => void;
  rowIndex: number;
}

function AppRow({ app, selected, onHover, onPick, rowIndex }: AppRowProps) {
  const Logo = getAppTypeLogo(app.appType);
  const unauth = !app.authenticated;
  return (
    <div className="cursor-pointer">
      <LineItem
        interactive={false}
        selected={selected}
        emphasized={selected}
        description={app.description}
        onMouseEnter={onHover}
        onMouseDown={(e) => {
          e.preventDefault();
          onPick();
        }}
        rightChildren={
          unauth ? (
            <Text font="secondary-action" color="text-03" nowrap>
              Connect
            </Text>
          ) : undefined
        }
        data-row-index={rowIndex}
        data-testid={`skill-picker-row-${app.slug}`}
      >
        <span
          className={cn(
            "inline-flex items-center gap-2",
            unauth && "opacity-50"
          )}
        >
          <Logo className="h-4 w-4 shrink-0" />
          <span>{`/${app.slug}`}</span>
        </span>
      </LineItem>
    </div>
  );
}

export default memo(EntryPickerPopover);
