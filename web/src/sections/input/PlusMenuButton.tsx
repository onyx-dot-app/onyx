"use client";

import { useState, useCallback, type ReactNode } from "react";
import { Button, Popover, Text } from "@opal/components";
import {
  SvgChevronRight,
  SvgPaperclip,
  SvgPlus,
  SvgSparkle,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import LineItem from "@/refresh-components/buttons/LineItem";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";
import type { PickerEntry, PickerSections } from "@/lib/skills/picker";

type FlyoutSection = "skills" | "apps";

export interface PlusMenuButtonProps {
  sections: PickerSections;
  onSelectEntry: (entry: PickerEntry) => void;
  onAttachFiles: () => void;
  disabled?: boolean;
}

interface FlyoutRowProps {
  icon: IconFunctionComponent;
  label: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onHoverOpen: () => void;
  children: ReactNode[];
}

// A menu row that opens a flyout panel anchored to its right. The panel is its
// own Popover nested inside the main menu's content; Radix treats nested
// portaled content as a dismissable-layer "branch", so interacting with the
// flyout doesn't close the main menu. Opens on hover (and click), matching the
// Anthropic composer menu.
function FlyoutRow({
  icon,
  label,
  open,
  onOpenChange,
  onHoverOpen,
  children,
}: FlyoutRowProps) {
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <Popover.Trigger asChild>
        <LineItem
          icon={icon}
          selected={open}
          onPointerEnter={onHoverOpen}
          rightChildren={<SvgChevronRight className="h-4 w-4 text-text-03" />}
        >
          {label}
        </LineItem>
      </Popover.Trigger>
      <Popover.Content
        side="right"
        align="start"
        sideOffset={8}
        width="lg"
        // Hover-opening shouldn't yank focus out of the textarea.
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <Popover.Menu>{children}</Popover.Menu>
      </Popover.Content>
    </Popover>
  );
}

export function PlusMenuButton({
  sections,
  onSelectEntry,
  onAttachFiles,
  disabled = false,
}: PlusMenuButtonProps) {
  const [open, setOpen] = useState(false);
  const [openSection, setOpenSection] = useState<FlyoutSection | null>(null);

  const close = useCallback(() => {
    setOpen(false);
    setOpenSection(null);
  }, []);

  const handleSelectEntry = useCallback(
    (entry: PickerEntry) => {
      onSelectEntry(entry);
      close();
    },
    [onSelectEntry, close]
  );

  const handleAttachFiles = useCallback(() => {
    onAttachFiles();
    close();
  }, [onAttachFiles, close]);

  // Single section open at a time. Functional updates keep the open/close
  // events from the two nested popovers from racing each other.
  const sectionOpenChange = useCallback(
    (section: FlyoutSection, next: boolean) => {
      setOpenSection((prev) =>
        next ? section : prev === section ? null : prev
      );
    },
    []
  );

  const hasSkills = sections.skills.length > 0;
  const hasApps = sections.apps.length > 0;

  const skillRows = sections.skills.map((skill) => (
    <LineItem
      key={`skill-${skill.slug}`}
      icon={SvgSparkle}
      description={skill.description}
      onClick={() => handleSelectEntry(skill)}
    >
      {skill.name}
    </LineItem>
  ));

  const appRows = sections.apps.map((app) => (
    <LineItem
      key={`app-${app.slug}`}
      icon={getAppTypeLogo(app.appType)}
      rightChildren={
        !app.authenticated ? (
          <Text font="secondary-body" color="text-03">
            Connect
          </Text>
        ) : undefined
      }
      onClick={() => handleSelectEntry(app)}
    >
      {app.name}
    </LineItem>
  ));

  // Flat array so a literal `null` renders as a Popover.Menu divider; a
  // divider sits between the Files action and the flyout rows when present.
  const menuChildren: ReactNode[] = [
    <LineItem
      key="files"
      icon={SvgPaperclip}
      onClick={handleAttachFiles}
      // Hovering a non-flyout row collapses any open flyout.
      onPointerEnter={() => setOpenSection(null)}
    >
      Add files or photos
    </LineItem>,
  ];

  if (hasSkills || hasApps) menuChildren.push(null);

  if (hasSkills) {
    menuChildren.push(
      <FlyoutRow
        key="skills"
        icon={SvgSparkle}
        label="Skills"
        open={openSection === "skills"}
        onOpenChange={(next) => sectionOpenChange("skills", next)}
        onHoverOpen={() => setOpenSection("skills")}
      >
        {skillRows}
      </FlyoutRow>
    );
  }

  if (hasApps) {
    menuChildren.push(
      <FlyoutRow
        key="apps"
        icon={getAppTypeLogo("CUSTOM")}
        label="Apps"
        open={openSection === "apps"}
        onOpenChange={(next) => sectionOpenChange("apps", next)}
        onHoverOpen={() => setOpenSection("apps")}
      >
        {appRows}
      </FlyoutRow>
    );
  }

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
        else setOpen(true);
      }}
    >
      <Popover.Trigger asChild>
        <Button
          icon={SvgPlus}
          prominence="tertiary"
          disabled={disabled}
          tooltip="Add files or skills"
          aria-label="Open add menu"
        />
      </Popover.Trigger>

      <Popover.Content side="top" align="start" width="lg">
        <Popover.Menu>{menuChildren}</Popover.Menu>
      </Popover.Content>
    </Popover>
  );
}

export default PlusMenuButton;
