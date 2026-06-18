import { PersonaSharePermission } from "@/lib/agents/types";
import { SvgBubbleText, SvgEdit, SvgLock, SvgOrganization } from "@opal/icons";
import { SharePermissionMenuOption } from "@/sections/modals/SharePermissionMenu";

export type ShareScope = "PRIVATE" | "PUBLIC";

export const PERMISSION_OPTIONS: SharePermissionMenuOption<PersonaSharePermission>[] =
  [
    {
      icon: SvgBubbleText,
      label: "View & Chat",
      value: "VIEWER",
    },
    {
      icon: SvgEdit,
      label: "Edit",
      value: "EDITOR",
    },
  ];

export const SCOPE_OPTIONS: SharePermissionMenuOption<ShareScope>[] = [
  {
    icon: SvgLock,
    label: "Only those invited",
    value: "PRIVATE",
  },
  {
    icon: SvgOrganization,
    label: "Anyone in your organization",
    value: "PUBLIC",
  },
];
