import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { SvgBubbleText, SvgEdit, SvgLock, SvgOrganization } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { SharePermissionMenuOption } from "@/sections/modals/SharePermissionMenu";

export type ShareScope = "PRIVATE" | "PUBLIC";
export type ShareAccessPermission = "EDITOR" | "VIEWER";

// Message keys under `chat.modals.share`, not copy — the literal union keeps
// `t()` statically checked while the definitions stay a plain module.
type ShareOptionLabelKey =
  | "permissionMenu.viewAndChat.label"
  | "permissionMenu.edit.label"
  | "scope.invitedOnly.label"
  | "scope.organization.label";

interface ShareOptionDefinition<T extends string> {
  value: T;
  icon: IconFunctionComponent;
  labelKey: ShareOptionLabelKey;
}

const PERMISSION_OPTION_DEFINITIONS: ShareOptionDefinition<ShareAccessPermission>[] =
  [
    {
      icon: SvgBubbleText,
      labelKey: "permissionMenu.viewAndChat.label",
      value: "VIEWER",
    },
    {
      icon: SvgEdit,
      labelKey: "permissionMenu.edit.label",
      value: "EDITOR",
    },
  ];

const SCOPE_OPTION_DEFINITIONS: ShareOptionDefinition<ShareScope>[] = [
  {
    icon: SvgLock,
    labelKey: "scope.invitedOnly.label",
    value: "PRIVATE",
  },
  {
    icon: SvgOrganization,
    labelKey: "scope.organization.label",
    value: "PUBLIC",
  },
];

export function useSharePermissionOptions(): SharePermissionMenuOption<ShareAccessPermission>[] {
  const t = useTranslations("chat.modals.share");
  return useMemo(
    () =>
      PERMISSION_OPTION_DEFINITIONS.map(({ icon, labelKey, value }) => ({
        icon,
        label: t(labelKey),
        value,
      })),
    [t]
  );
}

export function useShareScopeOptions(): SharePermissionMenuOption<ShareScope>[] {
  const t = useTranslations("chat.modals.share");
  return useMemo(
    () =>
      SCOPE_OPTION_DEFINITIONS.map(({ icon, labelKey, value }) => ({
        icon,
        label: t(labelKey),
        value,
      })),
    [t]
  );
}
