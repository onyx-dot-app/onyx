import type { IconFunctionComponent } from "@opal/types";
import { SvgSparkle } from "@opal/icons";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";
import { getActionIcon } from "@/lib/tools/utils";
import type { PickerEntry } from "@/lib/skills/picker";

/** Icon for a picker entry: the provider logo for apps, the server logo for MCP,
 * and the generic skill mark otherwise. Kept out of `picker.ts` so the data
 * module stays free of view imports, and shared so the three surfaces rendering
 * picker entries can't drift as the entry union grows. */
export function pickerEntryIcon(entry: PickerEntry): IconFunctionComponent {
  switch (entry.kind) {
    case "app":
      return getAppTypeLogo(entry.appType);
    case "mcp":
      return getActionIcon(entry.serverUrl, entry.name);
    case "skill":
      return SvgSparkle;
  }
}
