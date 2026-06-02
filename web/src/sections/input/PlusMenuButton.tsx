"use client";

import { useState, useCallback, type ReactNode } from "react";
import { Button, Popover, Text } from "@opal/components";
import {
  SvgChevronDown,
  SvgChevronRight,
  SvgPaperclip,
  SvgPlus,
  SvgSparkle,
} from "@opal/icons";
import LineItem from "@/refresh-components/buttons/LineItem";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";
import type { PickerEntry, PickerSections } from "@/lib/skills/picker";

export interface PlusMenuButtonProps {
  sections: PickerSections;
  onSelectEntry: (entry: PickerEntry) => void;
  onAttachFiles: () => void;
  disabled?: boolean;
}

export function PlusMenuButton({
  sections,
  onSelectEntry,
  onAttachFiles,
  disabled = false,
}: PlusMenuButtonProps) {
  const [open, setOpen] = useState(false);
  const [expandedSection, setExpandedSection] = useState<
    "skills" | "apps" | null
  >(null);

  const close = useCallback(() => {
    setOpen(false);
    setExpandedSection(null);
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

  const toggleSection = useCallback((section: "skills" | "apps") => {
    setExpandedSection((prev) => (prev === section ? null : section));
  }, []);

  const hasSkills = sections.skills.length > 0;
  const hasApps = sections.apps.length > 0;

  // Built as a flat array so a literal `null` between groups renders as a
  // Popover.Menu divider — a Fragment-wrapped null is passed as one non-null
  // child and never produces a separator.
  const menuChildren: ReactNode[] = [
    <LineItem key="files" icon={SvgPaperclip} onClick={handleAttachFiles}>
      Files
    </LineItem>,
  ];

  if (hasSkills) {
    menuChildren.push(null);
    menuChildren.push(
      <LineItem
        key="skills"
        icon={SvgSparkle}
        rightChildren={
          expandedSection === "skills" ? (
            <SvgChevronDown className="h-4 w-4 text-text-03" />
          ) : (
            <SvgChevronRight className="h-4 w-4 text-text-03" />
          )
        }
        onClick={() => toggleSection("skills")}
      >
        Skills
      </LineItem>
    );
    if (expandedSection === "skills") {
      for (const skill of sections.skills) {
        menuChildren.push(
          <LineItem
            key={`skill-${skill.slug}`}
            description={skill.description}
            muted
            onClick={() => handleSelectEntry(skill)}
          >
            {skill.name}
          </LineItem>
        );
      }
    }
  }

  if (hasApps) {
    menuChildren.push(null);
    for (const app of sections.apps) {
      const Logo = getAppTypeLogo(app.appType);
      menuChildren.push(
        <LineItem
          key={`app-${app.slug}`}
          icon={Logo}
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
      );
    }
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
