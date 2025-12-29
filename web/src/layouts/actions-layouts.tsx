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
 * import Switch from "@/components/ui/switch";
 *
 * function MyActionCard() {
 *   const { Provider } = useActionsLayout();
 *
 *   return (
 *     <Provider>
 *       <ActionsLayouts.Root>
 *         <ActionsLayouts.Header
 *           title="My MCP Server"
 *           description="A powerful MCP server for automation"
 *           icon={SvgServer}
 *           rightChildren={
 *             <Button onClick={handleDisconnect}>Disconnect</Button>
 *           }
 *         />
 *         <ActionsLayouts.Content>
 *           <ActionsLayouts.Tool
 *             title="File Reader"
 *             description="Read files from the filesystem"
 *             icon={SvgFile}
 *             rightChildren={
 *               <Switch checked={enabled} onCheckedChange={setEnabled} />
 *             }
 *           />
 *           <ActionsLayouts.Tool
 *             title="Web Search"
 *             description="Search the web"
 *             icon={SvgGlobe}
 *             disabled={true}
 *             rightChildren={
 *               <Switch checked={false} disabled />
 *             }
 *           />
 *         </ActionsLayouts.Content>
 *       </ActionsLayouts.Root>
 *     </Provider>
 *   );
 * }
 * ```
 */

"use client";

import React, {
  HtmlHTMLAttributes,
  createContext,
  useContext,
  useState,
  useMemo,
  Dispatch,
  SetStateAction,
  useCallback,
} from "react";
import { cn } from "@/lib/utils";
import type { IconProps } from "@opal/types";
import Truncated from "@/refresh-components/texts/Truncated";
import { WithoutStyles } from "@/types";
import Text from "@/refresh-components/texts/Text";
import { SvgMcp } from "@opal/icons";
import ShadowDiv from "@/refresh-components/ShadowDiv";

/**
 * Actions Layout Context
 *
 * Provides folding state management for action cards without prop drilling.
 */
interface ActionsLayoutContextValue {
  isFolded: boolean;
  setIsFolded: Dispatch<SetStateAction<boolean>>;
}

const ActionsLayoutContext = createContext<
  ActionsLayoutContextValue | undefined
>(undefined);

/**
 * Hook to create an ActionsLayout context provider and controller.
 *
 * @returns An object containing:
 *   - Provider: Context provider component to wrap action card
 *   - isFolded: Current folding state
 *   - setIsFolded: Function to update folding state
 *
 * @example
 * ```tsx
 * function MyActionCard() {
 *   const { Provider, isFolded, setIsFolded } = useActionsLayout();
 *
 *   return (
 *     <Provider>
 *       <ActionsLayouts.Root>
 *         <ActionsLayouts.Header
 *           title="My Server"
 *           description="Description"
 *           icon={SvgServer}
 *           rightChildren={
 *             <button onClick={() => setIsFolded(true)}>Fold</button>
 *           }
 *         />
 *         <ActionsLayouts.Content>
 *         </ActionsLayouts.Content>
 *       </ActionsLayouts.Root>
 *     </Provider>
 *   );
 * }
 * ```
 */
export function useActionsLayout() {
  const [isFolded, setIsFolded] = useState(false);
  const contextValue = useMemo(() => ({ isFolded, setIsFolded }), [isFolded]);

  // Wrap children directly, no component creation
  const Provider = useMemo(
    () =>
      ({ children }: { children: React.ReactNode }) => (
        <ActionsLayoutContext.Provider value={contextValue}>
          {children}
        </ActionsLayoutContext.Provider>
      ),
    [contextValue]
  );

  return { Provider, isFolded, setIsFolded };
}

/**
 * Internal hook to access the ActionsLayout context.
 */
function useActionsLayoutContext() {
  const context = useContext(ActionsLayoutContext);
  if (!context) {
    throw new Error(
      "ActionsLayout components must be used within an ActionsLayout Provider"
    );
  }
  return context;
}

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
  const { isFolded } = useActionsLayoutContext();

  return (
    <div
      className={cn(
        "flex flex-col border bg-background-neutral-00 w-full gap-2 pt-4 pb-2",
        isFolded ? "rounded-16" : "rounded-t-16"
      )}
    >
      <div className="px-4">
        <label
          className="flex items-start justify-between gap-2 cursor-pointer"
          htmlFor={name}
        >
          {/* Left: Icon, Title, Description */}
          <div className="flex flex-col items-start">
            <div className="flex items-center justify-center gap-2">
              <div className="min-w-[18px]">
                <Icon className="stroke-text-04" size={18} />
              </div>
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
 * Features a maximum height with scrollable overflow.
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
  const { isFolded } = useActionsLayoutContext();

  if (isFolded) {
    return null;
  }

  return (
    <div className="border-x border-b rounded-b-16 overflow-hidden">
      <ShadowDiv
        className="flex flex-col gap-2 rounded-b-16 max-h-[20rem] p-2"
        {...props}
      />
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
  icon: React.FunctionComponent<IconProps>;

  // State
  disabled?: boolean;
  rightChildren?: React.ReactNode;
}>;

function ActionsTool({
  name,
  title,
  description,
  icon: Icon,
  disabled,
  rightChildren,
}: ActionsToolProps) {
  return (
    <label
      className="flex items-start justify-between w-full p-3 rounded-12 border gap-2 bg-background-tint-00 cursor-pointer"
      htmlFor={name}
    >
      {/* Left Section: Icon and Content */}
      <div className="flex flex-col gap-1 items-start">
        {/* Icon Container */}
        <div className={cn("flex items-center justify-center gap-1")}>
          <Icon size={18} className="stroke-text-04" />
          <Truncated
            mainUiAction
            text04
            className={cn("truncate", disabled && "line-through")}
          >
            {title}
          </Truncated>
        </div>
        <Text
          as="p"
          text03
          secondaryBody
          className="whitespace-pre-wrap line-clamp-2 pl-6"
        >
          {description}
        </Text>
      </div>

      {/* Right Section */}
      {rightChildren}
    </label>
  );
}

/**
 * Actions No Tools Found Component
 *
 * A simple empty state component that displays when no tools are found.
 * Shows the MCP icon with "No tools found" message.
 *
 * @example
 * ```tsx
 * <ActionsLayouts.Content>
 *   {tools.length === 0 ? (
 *     <ActionsLayouts.NoToolsFound />
 *   ) : (
 *     tools.map(tool => <ActionsLayouts.Tool key={tool.id} {...tool} />)
 *   )}
 * </ActionsLayouts.Content>
 * ```
 */
function ActionsNoToolsFound() {
  return (
    <div className="flex items-center justify-center gap-2 p-4">
      <SvgMcp className="stroke-text-04" size={18} />
      <Text as="p" text03>
        No tools found
      </Text>
    </div>
  );
}

/**
 * Actions Tool Skeleton Component
 *
 * A loading skeleton that mimics the appearance of ActionsTool.
 * Renders 3 pulsing skeleton items to indicate loading state.
 *
 * Features:
 * - Animated pulsing effect
 * - Matches ActionsTool layout
 * - Renders 3 skeleton items by default
 *
 * @example
 * ```tsx
 * // Show loading state
 * <ActionsLayouts.Content>
 *   {isLoading ? (
 *     <ActionsLayouts.ToolSkeleton />
 *   ) : (
 *     tools.map(tool => <ActionsLayouts.Tool key={tool.id} {...tool} />)
 *   )}
 * </ActionsLayouts.Content>
 * ```
 */
function ActionsToolSkeleton() {
  return (
    <>
      {Array.from({ length: 3 }).map((_, index) => (
        <div
          key={index}
          className="flex items-start justify-between w-full p-3 rounded-12 border gap-2 bg-background-tint-00"
        >
          {/* Left Section: Icon and Content */}
          <div className="flex flex-col gap-1 items-start flex-1">
            {/* Icon and Title */}
            <div className="flex items-center gap-1 w-full">
              <div className="h-[18px] w-[18px] bg-background-neutral-02 rounded-04 animate-pulse" />
              <div className="h-4 bg-background-neutral-02 rounded-04 w-1/3 animate-pulse" />
            </div>
            {/* Description */}
            <div className="pl-6 w-full">
              <div className="h-3 bg-background-neutral-02 rounded-04 w-2/3 animate-pulse" />
            </div>
          </div>

          {/* Right Section: Switch skeleton */}
          <div className="h-5 w-10 bg-background-neutral-02 rounded-full animate-pulse" />
        </div>
      ))}
    </>
  );
}

export {
  ActionsRoot as Root,
  ActionsHeader as Header,
  ActionsContent as Content,
  ActionsTool as Tool,
  ActionsNoToolsFound as NoToolsFound,
  ActionsToolSkeleton as ToolSkeleton,
};
