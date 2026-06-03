import { Text } from "@opal/components";
import { SvgPaperclip, SvgPlug, SvgSparkle } from "@opal/icons";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";
import type { PickerEntry, PickerSections } from "@/lib/skills/picker";
import type { PlusMenuItem } from "@/sections/input/PlusMenuButton";

interface EntryMenuHandlers {
  onAttachFiles: () => void;
  onSelectEntry: (entry: PickerEntry) => void;
}

/** Maps picker sections onto the generic PlusMenuButton model. */
export function buildEntryMenuItems(
  sections: PickerSections,
  { onAttachFiles, onSelectEntry }: EntryMenuHandlers
): Array<PlusMenuItem | null> {
  const items: Array<PlusMenuItem | null> = [
    {
      key: "files",
      icon: SvgPaperclip,
      label: "Add files or photos",
      onSelect: onAttachFiles,
    },
  ];

  if (sections.skills.length > 0 || sections.apps.length > 0) {
    items.push(null);
  }

  if (sections.skills.length > 0) {
    items.push({
      key: "skills",
      icon: SvgSparkle,
      label: "Skills",
      flyoutItems: sections.skills.map((skill) => ({
        key: skill.slug,
        icon: SvgSparkle,
        label: skill.name,
        description: skill.description,
        onSelect: () => onSelectEntry(skill),
      })),
    });
  }

  if (sections.apps.length > 0) {
    items.push({
      key: "apps",
      icon: SvgPlug,
      label: "Apps",
      flyoutItems: sections.apps.map((app) => ({
        key: app.slug,
        icon: getAppTypeLogo(app.appType),
        label: app.name,
        rightContent: app.authenticated ? undefined : (
          <Text font="secondary-body" color="text-03">
            Connect
          </Text>
        ),
        onSelect: () => onSelectEntry(app),
      })),
    });
  }

  return items;
}
