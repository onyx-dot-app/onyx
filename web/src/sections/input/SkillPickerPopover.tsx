"use client";

import { memo, useEffect, useMemo, useRef, useState } from "react";
import { Popover, Text } from "@opal/components";
import LineItem from "@/refresh-components/buttons/LineItem";
import { filterPickerSkills, type PickerSkill } from "@/lib/skills/picker";

interface SkillPickerPopoverProps {
  open: boolean;
  anchorRect: DOMRect | null;
  query: string;
  skills: PickerSkill[];
  onSelect: (slug: string) => void;
  onClose: () => void;
}

// Floating popover for the `/` skill picker. Visually mirrors the
// Prompt Shortcuts dropdown by reusing Opal's `Popover` + `Popover.Menu` +
// `LineItem`. Positioning is driven by a hidden zero-width anchor element
// placed at the caret (for contentEditable inputs) or at the textarea rect
// (for the schedule-task form), since Radix Popover positions relative to a
// DOM anchor rather than a virtual rect. A global keydown listener handles
// arrow / Enter / Tab / Escape so the host input keeps focus.
function SkillPickerPopover({
  open,
  anchorRect,
  query,
  skills,
  onSelect,
  onClose,
}: SkillPickerPopoverProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(
    () => filterPickerSkills(skills, query),
    [skills, query]
  );

  useEffect(() => {
    setSelectedIndex(0);
  }, [open, query]);

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
        if (filtered.length === 0) return;
        setSelectedIndex((i) => (i + 1) % filtered.length);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        e.stopPropagation();
        if (filtered.length === 0) return;
        setSelectedIndex((i) => (i - 1 + filtered.length) % filtered.length);
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        e.stopPropagation();
        if (filtered.length === 0) {
          onClose();
          return;
        }
        const skill = filtered[selectedIndex] ?? filtered[0];
        if (skill) onSelect(skill.slug);
      } else if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    }

    document.addEventListener("keydown", handleKeyDown, true);
    return () => document.removeEventListener("keydown", handleKeyDown, true);
  }, [open, filtered, selectedIndex, onSelect, onClose]);

  if (!anchorRect) return null;

  return (
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
          {filtered.length === 0
            ? [
                <div key="empty" className="p-2">
                  <Text font="secondary-body" color="text-03">
                    No matching skills
                  </Text>
                </div>,
              ]
            : filtered.map((skill, idx) => {
                const isSelected = idx === selectedIndex;
                const description = skill.description;
                return (
                  <LineItem
                    key={skill.slug}
                    interactive={false}
                    selected={isSelected}
                    emphasized={isSelected}
                    description={description}
                    onMouseEnter={() => setSelectedIndex(idx)}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      onSelect(skill.slug);
                    }}
                    data-row-index={idx}
                    data-testid={`skill-picker-row-${skill.slug}`}
                  >
                    {`/${skill.slug}`}
                  </LineItem>
                );
              })}
        </Popover.Menu>
      </Popover.Content>
    </Popover>
  );
}

export default memo(SkillPickerPopover);
