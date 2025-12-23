/**
 * Admin Page Layout Components
 *
 * Layout components specifically designed for admin/configuration pages.
 * Provides a consistent structure with header, separator, and scrollable content area.
 *
 * Features:
 * - Fixed maximum width container (60rem)
 * - Header with icon, title, and description
 * - Horizontal separator between header and content
 * - Scrollable content area
 * - Full-height layout with proper overflow handling
 *
 * @example
 * ```tsx
 * import { AdminPageLayout } from "@/layouts/admin-pages";
 * import { SvgSettings } from "@opal/icons";
 *
 * export default function AdminSettingsPage() {
 *   return (
 *     <AdminPageLayout
 *       icon={SvgSettings}
 *       title="System Settings"
 *       description="Configure system-wide settings and preferences"
 *       rightChildren={<Button>Save All</Button>}
 *     >
 *       <Card>Settings form content</Card>
 *       <Card>More settings</Card>
 *     </AdminPageLayout>
 *   );
 * }
 * ```
 */

"use client";

import Text from "@/refresh-components/texts/Text";
import Separator from "@/refresh-components/Separator";
import type { IconProps } from "@opal/types";

/**
 * Admin Page Header Component
 *
 * Header component for admin pages showing icon, title, description,
 * and optional action buttons. Typically used internally by AdminPageLayout
 * but can also be used standalone.
 *
 * Features:
 * - Icon display (1.75rem size)
 * - Title with aria-label for accessibility
 * - Secondary description text
 * - Optional right-aligned action area
 *
 * @example
 * ```tsx
 * // Standalone usage (rare)
 * <AdminPageHeader
 *   icon={SvgDatabase}
 *   title="Data Connectors"
 *   description="Manage your data source connections"
 *   rightChildren={<Button>Add Connector</Button>}
 * />
 *
 * // Usually used via AdminPageLayout
 * <AdminPageLayout
 *   icon={SvgDatabase}
 *   title="Data Connectors"
 *   description="Manage your data source connections"
 * >
 *   {children}
 * </AdminPageLayout>
 * ```
 */
export interface AdminPageHeaderProps {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description: string;
  rightChildren?: React.ReactNode;
}

export function AdminPageHeader({
  icon: Icon,
  title,
  description,
  rightChildren,
}: AdminPageHeaderProps) {
  return (
    <div className="flex flex-col">
      <div className="flex flex-row justify-between items-center gap-4">
        <Icon className="stroke-text-04 h-[1.75rem] w-[1.75rem]" />
        {rightChildren}
      </div>
      <div className="flex flex-col">
        <Text headingH2>{title}</Text>
        <Text secondaryBody text03>
          {description}
        </Text>
      </div>
    </div>
  );
}

/**
 * Admin Page Layout Component
 *
 * Complete page layout for admin/configuration pages. Combines header,
 * separator, and scrollable content area into a single component.
 *
 * Features:
 * - Full height container with overflow handling
 * - Maximum width of 60rem (centered)
 * - Fixed header section with AdminPageHeader and separator
 * - Flexible, scrollable content area
 * - Consistent spacing and padding
 *
 * Layout Structure:
 * ```
 * ┌─────────────────────────────────┐
 * │ Header (icon, title, desc)      │
 * ├─────────────────────────────────┤ ← Separator
 * │                                 │
 * │ Scrollable Content Area         │
 * │ (children)                      │
 * │                                 │
 * └─────────────────────────────────┘
 * ```
 *
 * @example
 * ```tsx
 * // Basic admin page
 * <AdminPageLayout
 *   icon={SvgActions}
 *   title="OpenAPI Actions"
 *   description="Connect OpenAPI servers to add custom actions"
 * >
 *   <OpenApiPageContent />
 * </AdminPageLayout>
 *
 * // With action buttons in header
 * <AdminPageLayout
 *   icon={SvgMcp}
 *   title="MCP Servers"
 *   description="Manage Model Context Protocol servers"
 *   rightChildren={
 *     <Button onClick={handleAddServer}>Add Server</Button>
 *   }
 * >
 *   <ServerList servers={servers} />
 *   <ServerConfiguration />
 * </AdminPageLayout>
 *
 * // Multiple content sections
 * <AdminPageLayout
 *   icon={SvgSettings}
 *   title="Advanced Configuration"
 *   description="Expert-level system settings"
 * >
 *   <Card>Section 1</Card>
 *   <Card>Section 2</Card>
 *   <Card>Section 3</Card>
 * </AdminPageLayout>
 * ```
 */
export interface AdminPageLayoutProps {
  children: React.ReactNode;
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description: string;
  rightChildren?: React.ReactNode;
}

export function AdminPageLayout({
  children,
  icon,
  title,
  description,
  rightChildren,
}: AdminPageLayoutProps) {
  return (
    <div className="flex flex-col w-full h-full overflow-hidden">
      <div className="container max-w-[60rem] flex flex-col h-full overflow-hidden">
        <div className="px-4 pt-14 pb-6 gap-6 flex flex-col flex-shrink-0">
          <AdminPageHeader
            icon={icon}
            title={title}
            description={description}
            rightChildren={rightChildren}
          />
          <Separator className="py-0" />
        </div>
        <div className="px-4 pb-6 flex-1 overflow-y-auto min-h-0">
          {children}
        </div>
      </div>
    </div>
  );
}
