import { Text } from "@opal/components";
import {
  SvgFileText,
  SvgFolder,
  SvgPaperclip,
  SvgPlug,
  SvgSparkle,
} from "@opal/icons";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";
import type { PickerEntry, PickerSections } from "@/lib/skills/picker";
import type { PlusMenuItem } from "@/sections/input/PlusMenuButton";

interface LibraryFile {
  id: string;
  name: string;
}

interface EntryMenuHandlers {
  onAttachFiles: () => void;
  onSelectEntry: (entry: PickerEntry) => void;
  // Navigate to the Skills / Apps pages (used by the empty-state prompts).
  onBrowseSkills: () => void;
  onBrowseApps: () => void;
  libraryFiles?: LibraryFile[];
  /** Opens the library management modal. When set, a Library flyout is added. */
  onManageLibrary?: () => void;
}

/** Maps picker sections onto the generic PlusMenuButton model. */
export function buildEntryMenuItems(
  sections: PickerSections,
  {
    onAttachFiles,
    onSelectEntry,
    onBrowseSkills,
    onBrowseApps,
    libraryFiles = [],
    onManageLibrary,
  }: EntryMenuHandlers
): Array<PlusMenuItem | null> {
  // Skills and Apps always show; when empty they prompt the user to browse/connect.
  const items: Array<PlusMenuItem | null> = [
    {
      key: "files",
      icon: SvgPaperclip,
      label: "Add files or photos",
      onSelect: onAttachFiles,
    },
    null,
    {
      key: "skills",
      icon: SvgSparkle,
      label: "Skills",
      flyoutItems:
        sections.skills.length > 0
          ? sections.skills.map((skill) => ({
              key: skill.slug,
              icon: SvgSparkle,
              label: skill.name,
              description: skill.description,
              onSelect: () => onSelectEntry(skill),
            }))
          : [
              {
                key: "skills-empty",
                icon: SvgSparkle,
                label: "Browse skills",
                onSelect: onBrowseSkills,
              },
            ],
    },
    {
      key: "apps",
      icon: SvgPlug,
      label: "Apps",
      flyoutItems:
        sections.apps.length > 0
          ? sections.apps.map((app) => ({
              key: app.slug,
              icon: getAppTypeLogo(app.appType),
              label: app.name,
              rightContent: app.authenticated ? undefined : (
                <Text font="secondary-body" color="text-03">
                  Connect
                </Text>
              ),
              onSelect: () => onSelectEntry(app),
            }))
          : [
              {
                key: "apps-empty",
                icon: SvgPlug,
                label: "Connect an app",
                onSelect: onBrowseApps,
              },
            ],
    },
  ];

  if (onManageLibrary) {
    items.push({
      key: "library",
      icon: SvgFolder,
      label: "Library",
      flyoutItems: [
        // TODO(craft-library): file rows open the manage modal until per-file attach is wired.
        ...libraryFiles.map((file) => ({
          key: file.id,
          icon: SvgFileText,
          label: file.name,
          onSelect: onManageLibrary,
        })),
        {
          key: "manage",
          icon: SvgFolder,
          label: "Manage library…",
          onSelect: onManageLibrary,
        },
      ],
    });
  }

  return items;
}
