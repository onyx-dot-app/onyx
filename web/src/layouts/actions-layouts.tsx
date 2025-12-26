/**
 * Actions Layout Components
 *
 * A namespaced collection of components for building consistent action cards
 * (MCP servers, OpenAPI tools, etc.). These components provide a standardized
 * layout that separates presentation from business logic, making it easier to
 * build and maintain action-related UIs.
 *
 * @example
 * ```tsx
 * import * as ActionsLayouts from "@/layouts/actions-layouts";
 * import { SvgServer } from "@opal/icons";
 *
 * function MyActionCard() {
 *   const [isExpanded, setIsExpanded] = useState(false);
 *
 *   return (
 *     <ActionsLayouts.Root>
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
 *           name="file_reader"
 *           description="Read files from the filesystem"
 *           isEnabled={true}
 *           onToggle={(enabled) => handleToolToggle('file_reader', enabled)}
 *         />
 *         <ActionsLayouts.Tool
 *           name="web_search"
 *           description="Search the web"
 *           isEnabled={false}
 *           onToggle={(enabled) => handleToolToggle('web_search', enabled)}
 *         />
 *       </ActionsLayouts.Content>
 *     </ActionsLayouts.Root>
 *   );
 * }
 * ```
 */

"use client";

import React, { HtmlHTMLAttributes } from "react";
import { cn } from "@/lib/utils";
import type { IconProps } from "@opal/types";
import { SvgAlertTriangle } from "@opal/icons";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import Switch from "@/refresh-components/inputs/Switch";
import { WithoutStyles } from "@/types";

/**
 * Actions Root Component
 *
 * The root container for an action card. Simply provides a flex column layout.
 * Use this as the outermost wrapper for action cards.
 *
 * @example
 * ```tsx
 * <ActionsLayouts.Root>
 *   <ActionsLayouts.Header {...} />
 *   <ActionsLayouts.Content {...} />
 * </ActionsLayouts.Root>
 * ```
 */
export type ActionsRootProps = WithoutStyles<
  React.HTMLAttributes<HTMLDivElement>
>;

function ActionsRoot(props: ActionsRootProps) {
  return <div className="flex flex-col" {...props} />;
}

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
export type ActionsHeaderProps = WithoutStyles<
  {
    // Core content
    name?: string;
    title: string;
    description: string;
    icon: React.FunctionComponent<IconProps>;

    // Custom content
    rightChildren?: React.ReactNode;
  } & HtmlHTMLAttributes<HTMLDivElement>
>;

function ActionsHeader({
  name,
  title,
  description,
  icon: Icon,
  rightChildren,

  ...props
}: ActionsHeaderProps) {
  return (
    <div className="flex flex-col border rounded-16 bg-background-neutral-00 w-full gap-2 pt-4 pb-2">
      <div className="px-4">
        <label
          className="flex items-start justify-between gap-2 cursor-pointer"
          htmlFor={name}
        >
          {/* Left: Icon, Title, Description */}
          <div className="flex flex-col items-start">
            <div className="flex items-center justify-center gap-2">
              <Icon className="stroke-text-04" size={18} />
              <Truncated mainContentEmphasis text04>
                {title}
              </Truncated>
            </div>
            <Truncated secondaryBody text03 className="pl-7">
              {description}
            </Truncated>
          </div>

          {/* Right: Actions */}
          {rightChildren}
        </label>
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
export type ActionsContentProps = WithoutStyles<
  React.HTMLAttributes<HTMLDivElement>
>;

function ActionsContent(props: ActionsContentProps) {
  return <div className="flex flex-col" {...props} />;
}

/**
 * Actions Tool Component
 *
 * Represents a single tool within an actions content area. Displays the tool's
 * name, description, icon, availability status, and provides a toggle for
 * enabling/disabling the tool.
 *
 * Features:
 * - Tool name and description
 * - Optional custom icon
 * - Availability indicator (with warning badge and strikethrough)
 * - Enable/disable toggle switch
 * - Disabled state when tool is unavailable
 * - Responsive layout with truncated text
 *
 * @example
 * ```tsx
 * // Basic tool
 * <ActionsLayouts.Tool
 *   name="file_read"
 *   description="Read files from the filesystem"
 *   isEnabled={true}
 *   onToggle={(enabled) => handleToggle('file_read', enabled)}
 * />
 *
 * // With custom icon
 * <ActionsLayouts.Tool
 *   name="web_search"
 *   description="Search the web for information"
 *   icon={SvgGlobe}
 *   isAvailable={true}
 *   isEnabled={false}
 *   onToggle={(enabled) => handleToggle('web_search', enabled)}
 * />
 *
 * // Unavailable tool
 * <ActionsLayouts.Tool
 *   name="premium_feature"
 *   description="This feature requires a premium subscription"
 *   isAvailable={false}
 *   isEnabled={false}
 * />
 * ```
 */
export type ActionsToolProps = WithoutStyles<{
  // Core content
  name: string;
  description: string;
  icon?: React.FunctionComponent<IconProps>;

  // State
  isAvailable?: boolean;
  isEnabled: boolean;
  onToggle?: (enabled: boolean) => void;
}>;

function ActionsTool(props: ActionsToolProps) {
  const {
    name,
    description,
    icon: Icon,
    isAvailable = true,
    isEnabled = true,
    onToggle,
  } = props;

  const unavailableStyles = !isAvailable
    ? "bg-background-neutral-02"
    : "bg-background-tint-00";

  const textOpacity = !isAvailable ? "opacity-50" : "";

  return (
    <div
      className={cn(
        "flex items-start justify-between w-full p-2 rounded-08 border border-border-01 gap-2",
        unavailableStyles
      )}
    >
      {/* Left Section: Icon and Content */}
      <div className="flex gap-1 items-start flex-1 min-w-0 pr-2">
        {/* Icon Container */}
        {Icon && (
          <div
            className={cn(
              "flex items-center justify-center shrink-0",
              textOpacity
            )}
          >
            <Icon size={20} className="h-5 w-5 stroke-text-04" />
          </div>
        )}

        {/* Content Container */}
        <div className="flex flex-col items-start flex-1 min-w-0">
          {/* Tool Name */}
          <div className="flex items-center w-full min-h-[20px] px-0.5">
            <Truncated
              mainUiAction
              text04
              className={cn(
                "truncate",
                textOpacity,
                !isAvailable && "line-through"
              )}
            >
              {name}
            </Truncated>
          </div>

          {/* Description */}
          <div className="px-0.5 w-full">
            <Truncated
              text03
              secondaryBody
              className={cn("whitespace-pre-wrap", textOpacity)}
            >
              {description}
            </Truncated>
          </div>
        </div>
      </div>

      {/* Right Section */}
      <div className="flex gap-2 items-start justify-end shrink-0">
        {/* Unavailable Badge */}
        {!isAvailable && (
          <div className="flex items-center min-h-[20px] px-0 py-0.5">
            <div className="flex gap-0.5 items-center">
              <div className="flex items-center px-0.5">
                <Text text03 secondaryBody className="text-right">
                  Tool unavailable
                </Text>
              </div>
              <div className="flex items-center justify-center p-0.5 w-4 h-4">
                <SvgAlertTriangle className="w-3 h-3 stroke-status-warning-05" />
              </div>
            </div>
          </div>
        )}

        {/* Switch */}
        <div className="flex items-center justify-center gap-1 h-5 px-0.5 py-0.5">
          <Switch
            checked={isEnabled}
            onCheckedChange={onToggle}
            disabled={!isAvailable}
            aria-label={`tool-toggle-${name}`}
          />
        </div>
      </div>
    </div>
  );
}

export {
  ActionsRoot as Root,
  ActionsHeader as Header,
  ActionsContent as Content,
  ActionsTool as Tool,
};
