import { IconFunctionComponent } from "@opal/types";
import { SvgArrowUpCircle } from "@opal/icons";
import {
  ADMIN_ROUTES,
  AdminRouteEntry,
  FeatureFlags,
  sidebarItem,
} from "@/lib/admin-routes";
import { hasPermission } from "@/lib/permissions";
import { Permission } from "@/lib/types";
import { Settings, Tier } from "@/lib/settings/types";
import { tierAtLeast } from "@/lib/tiers";

export type { FeatureFlags } from "@/lib/admin-routes";

export interface SidebarItemEntry {
  section: string;
  name: string;
  icon: IconFunctionComponent;
  link: string;
  error?: boolean;
  disabled?: boolean;
  requiredTier?: Tier | null;
}

export function buildItems(
  permissions: string[],
  flags: FeatureFlags,
  settings: Settings | null
): SidebarItemEntry[] {
  const userCanAccess = (perm: string) => hasPermission(permissions, perm);
  const items: SidebarItemEntry[] = [];

  for (const route of Object.values(ADMIN_ROUTES) as AdminRouteEntry[]) {
    if (!route.sidebarLabel) continue;
    if (!userCanAccess(route.requiredPermission)) continue;
    if (route.visibleWhen && !route.visibleWhen(flags)) continue;

    const disabled =
      route.requiredTier !== null &&
      !tierAtLeast(flags.tier, route.requiredTier);

    const item: SidebarItemEntry = {
      ...sidebarItem(route),
      section: route.section,
      disabled,
      requiredTier: route.requiredTier,
    };

    // INDEX_SETTINGS surfaces a reindexing-needed error indicator
    if (route.path === ADMIN_ROUTES.INDEX_SETTINGS.path) {
      item.error = settings?.needs_reindexing;
    }

    items.push(item);
  }

  if (
    userCanAccess(Permission.FULL_ADMIN_PANEL_ACCESS) &&
    !flags.hasSubscription
  ) {
    items.push({
      section: "",
      name: "Upgrade Plan",
      icon: SvgArrowUpCircle,
      link: ADMIN_ROUTES.BILLING.path,
    });
  }

  return items;
}

/** Preserve section ordering while grouping consecutive items by section. */
export function groupBySection(items: SidebarItemEntry[]) {
  const groups: { section: string; items: SidebarItemEntry[] }[] = [];
  for (const item of items) {
    const last = groups[groups.length - 1];
    if (last && last.section === item.section) {
      last.items.push(item);
    } else {
      groups.push({ section: item.section, items: [item] });
    }
  }
  return groups;
}
