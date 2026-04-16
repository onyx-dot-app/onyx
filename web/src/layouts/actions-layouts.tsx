/**
 * Actions Layout Components
 *
 * A namespaced collection of layout primitives for building consistent action
 * cards (MCP servers, OpenAPI tools, etc.). These render the inner layout of
 * an action card (title row + optional search/controls row for `Header`; list
 * of tools for `Content`) and do NOT provide any outer card chrome
 * themselves — callers wrap these with an Opal `Card` (plain or `expandable`)
 * to supply border, background, rounding, and fold animation.
 *
 * @example
 * ```tsx
 * import * as ActionsLayouts from "@/layouts/actions-layouts";
 * import { Card } from "@opal/components";
 * import { SvgServer } from "@opal/icons";
 * import Switch from "@/components/ui/switch";
 *
 * function MyActionCard() {
 *   const [expanded, setExpanded] = useState(false);
 *   return (
 *     <Card
 *       expandable
 *       expanded={expanded}
 *       border="solid"
 *       rounding="lg"
 *       padding="fit"
 *       content={
 *         <ActionsLayouts.Content>
 *           <ActionsLayouts.Tool
 *             title="File Reader"
 *             description="Read files from the filesystem"
 *             icon={SvgFile}
 *             rightChildren={
 *               <Switch checked={enabled} onCheckedChange={setEnabled} />
 *             }
 *           />
 *         </ActionsLayouts.Content>
 *       }
 *     >
 *       <ActionsLayouts.Header
 *         title="My MCP Server"
 *         description="A powerful MCP server for automation"
 *         icon={SvgServer}
 *         rightChildren={
 *           <Button onClick={() => setExpanded((v) => !v)}>Toggle</Button>
 *         }
 *       />
 *     </Card>
 *   );
 * }
 * ```
 */

"use client";

import React, { HtmlHTMLAttributes } from "react";
import type { IconProps } from "@opal/types";
import { WithoutStyles } from "@/types";
import { ContentAction } from "@opal/layouts";
import { Card } from "@/refresh-components/cards";
import { Label } from "@opal/layouts";

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
    <div className="flex flex-col gap-2 pt-4 pb-2">
      <div className="px-4">
        <Label label={name}>
          <ContentAction
            icon={Icon}
            title={title}
            description={description}
            sizePreset="section"
            variant="section"
            rightChildren={rightChildren}
            paddingVariant="fit"
          />
        </Label>
      </div>
      <div {...props} className="px-2" />
    </div>
  );
}

/**
 * Actions Content Component
 *
 * A container for the content area of an action card.
 * Use this to wrap tools, settings, or other expandable content.
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
    <div {...props} className="flex flex-col gap-2 p-2">
      {children}
    </div>
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
      <Label label={name} disabled={disabled}>
        <ContentAction
          icon={icon}
          title={title}
          description={description}
          sizePreset="main-ui"
          variant="section"
          rightChildren={rightChildren}
          paddingVariant="fit"
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
