/**
 * Actions Layout Components
 *
 * A namespaced collection of components for building consistent action cards
 * (MCP servers, OpenAPI tools, etc.). These components provide a standardized
 * layout that separates presentation from business logic, making it easier to
 * build and maintain action-related UIs.
 *
 * Built on top of ExpandableCard layouts for the underlying card structure.
 *
 * @example
 * ```tsx
 * import * as ActionsLayouts from "@/layouts/actions-layouts";
 * import * as ExpandableCard from "@/layouts/expandable-card-layouts";
 * import { SvgServer } from "@opal/icons";
 * import Switch from "@/components/ui/switch";
 *
 * function MyActionCard() {
 *   return (
 *     <ExpandableCard.Root>
 *       <ActionsLayouts.Header
 *         title="My MCP Server"
 *         description="A powerful MCP server for automation"
 *         icon={SvgServer}
 *         rightChildren={
 *           <Button onClick={handleDisconnect}>Disconnect</Button>
 *         }
 *       />
 *       <ActionsLayouts.Content>
 *         <ActionsLayouts.Tool
 *           title="File Reader"
 *           description="Read files from the filesystem"
 *           icon={SvgFile}
 *           rightChildren={
 *             <Switch checked={enabled} onCheckedChange={setEnabled} />
 *           }
 *         />
 *         <ActionsLayouts.Tool
 *           title="Web Search"
 *           description="Search the web"
 *           icon={SvgGlobe}
 *           disabled={true}
 *           rightChildren={
 *             <Switch checked={false} disabled />
 *           }
 *         />
 *       </ActionsLayouts.Content>
 *     </ExpandableCard.Root>
 *   );
 * }
 * ```
 */

"use client";

import React, { HtmlHTMLAttributes } from "react";
import type { IconProps } from "@opal/types";
import { WithoutStyles } from "@/types";
import { LineItemLayout } from "@/layouts/general-layouts";
import * as ExpandableCard from "@/layouts/expandable-card-layouts";
import { Card } from "@/refresh-components/cards";
import Label from "@/refresh-components/form/Label";

/**
 * Actions Header Component
 *
 * The header section of an action card. Displays icon, title, description,
 * and optional right-aligned actions.
 *
 * Features:
 * - Icon, title, and description display
 * - Custom right-aligned actions via rightChildren
 * - Responsive layout with truncated text
 *
 * @example
 * ```tsx
 * // Basic header
 * <ActionsLayouts.Header
 *   title="File Server"
 *   description="Manage local files"
 *   icon={SvgFolder}
 * />
 *
 * // With actions
 * <ActionsLayouts.Header
 *   title="API Server"
 *   description="RESTful API integration"
 *   icon={SvgCloud}
 *   rightChildren={
 *     <div className="flex gap-2">
 *       <Button onClick={handleEdit}>Edit</Button>
 *       <Button onClick={handleDelete}>Delete</Button>
 *     </div>
 *   }
 * />
 * ```
 */
export interface ActionsHeaderProps
  extends WithoutStyles<HtmlHTMLAttributes<HTMLDivElement>> {
  // Core content
  name?: string;
  title: string;
  description?: string;
  icon: React.FunctionComponent<IconProps>;

  // Custom content
  rightChildren?: React.ReactNode;
}
function ActionsHeader({
  name,
  title,
  description,
  icon: Icon,
  rightChildren,
  ...props
}: ActionsHeaderProps) {
  return (
    <ExpandableCard.Header>
      <div className="flex flex-col gap-2 pt-4 pb-2">
        <div className="px-4">
          <Label name={name}>
            <LineItemLayout
              icon={Icon}
              title={title}
              description={description}
              rightChildren={rightChildren}
            />
          </Label>
        </div>
        <div {...props} className="px-2" />
      </div>
    </ExpandableCard.Header>
  );
}

/**
 * Actions Content Component
 *
 * A container for the content area of an action card.
 * Use this to wrap tools, settings, or other expandable content.
 * Features a maximum height with scrollable overflow.
 *
 * IMPORTANT: Only ONE ActionsContent should be used within a single ExpandableCard.Root.
 * This component self-registers with the ActionsLayout context to inform
 * ActionsHeader whether content exists (for border-radius styling). Using
 * multiple ActionsContent components will cause incorrect unmount behavior -
 * when any one unmounts, it will incorrectly signal that no content exists,
 * even if other ActionsContent components remain mounted.
 *
 * @example
 * ```tsx
 * <ActionsLayouts.Content>
 *   <ActionsLayouts.Tool {...} />
 *   <ActionsLayouts.Tool {...} />
 * </ActionsLayouts.Content>
 * ```
 */
function ActionsContent({
  children,
  ...props
}: WithoutStyles<React.HTMLAttributes<HTMLDivElement>>) {
  return (
    <ExpandableCard.Content {...props}>
      <div className="flex flex-col gap-2 p-2">{children}</div>
    </ExpandableCard.Content>
  );
}

/**
 * Actions Tool Component
 *
 * Represents a single tool within an actions content area. Displays the tool's
 * title, description, and icon. The component provides a label wrapper for
 * custom right-aligned controls (like toggle switches).
 *
 * Features:
 * - Tool title and description
 * - Custom icon
 * - Disabled state (applies strikethrough to title)
 * - Custom right-aligned content via rightChildren
 * - Responsive layout with truncated text
 *
 * @example
 * ```tsx
 * // Basic tool with switch
 * <ActionsLayouts.Tool
 *   title="File Reader"
 *   description="Read files from the filesystem"
 *   icon={SvgFile}
 *   rightChildren={
 *     <Switch checked={enabled} onCheckedChange={setEnabled} />
 *   }
 * />
 *
 * // Disabled tool
 * <ActionsLayouts.Tool
 *   title="Premium Feature"
 *   description="This feature requires a premium subscription"
 *   icon={SvgLock}
 *   disabled={true}
 *   rightChildren={
 *     <Switch checked={false} disabled />
 *   }
 * />
 *
 * // Tool with custom action
 * <ActionsLayouts.Tool
 *   name="config_tool"
 *   title="Configuration"
 *   description="Configure system settings"
 *   icon={SvgSettings}
 *   rightChildren={
 *     <Button onClick={openSettings}>Configure</Button>
 *   }
 * />
 * ```
 */
export type ActionsToolProps = WithoutStyles<{
  // Core content
  name?: string;
  title: string;
  description: string;
  icon?: React.FunctionComponent<IconProps>;

  // State
  disabled?: boolean;
  rightChildren?: React.ReactNode;
}>;
function ActionsTool({
  name,
  title,
  description,
  icon,
  disabled,
  rightChildren,
}: ActionsToolProps) {
  return (
    <Card padding={0.75} variant={disabled ? "disabled" : undefined}>
      <Label name={name} disabled={disabled}>
        <LineItemLayout
          icon={icon}
          title={title}
          description={description}
          rightChildren={rightChildren}
          variant="secondary"
        />
      </Label>
    </Card>
  );
}

export {
  ActionsHeader as Header,
  ActionsContent as Content,
  ActionsTool as Tool,
};
