import { Text } from "@opal/components";
import {
  SvgFileText,
  SvgFolder,
  SvgPaperclip,
  SvgPlug,
  SvgSparkle,
} from "@opal/icons";
import {
  pickerEntryKey,
  type PickerEntry,
  type PickerSections,
} from "@/lib/skills/picker";
import { pickerEntryIcon } from "@/lib/skills/pickerIcons";
import type {
  PlusMenuFlyoutItem,
  PlusMenuItem,
} from "@/sections/input/PlusMenuButton";

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
      flyoutItems: buildAppFlyoutItems(sections, {
        onSelectEntry,
        onBrowseApps,
      }),
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

interface AppFlyoutHandlers {
  onSelectEntry: (entry: PickerEntry) => void;
  onBrowseApps: () => void;
}

/** Apps and craft-enabled MCP servers share this flyout — the agent reaches
 * both the same way from the user's point of view. MCP rows are labelled so the
 * two never read as one kind of thing. */
function buildAppFlyoutItems(
  sections: PickerSections,
  { onSelectEntry, onBrowseApps }: AppFlyoutHandlers
): PlusMenuFlyoutItem[] {
  const connectHint = (authenticated: boolean) =>
    authenticated ? undefined : (
      <Text font="secondary-body" color="text-03">
        Connect
      </Text>
    );

  const items: PlusMenuFlyoutItem[] = [
    ...sections.apps,
    ...sections.mcpServers,
  ].map((entry) => ({
    key: pickerEntryKey(entry),
    icon: pickerEntryIcon(entry),
    label: entry.name,
    // Only MCP rows are labelled; apps are the default kind on this page.
    description: entry.kind === "mcp" ? "MCP server" : undefined,
    rightContent: connectHint(entry.authenticated),
    onSelect: () => onSelectEntry(entry),
  }));

  return items.length > 0
    ? items
    : [
        {
          key: "apps-empty",
          icon: SvgPlug,
          label: "Connect an app",
          onSelect: onBrowseApps,
        },
      ];
}
