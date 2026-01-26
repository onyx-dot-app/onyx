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
  useRef,
  useLayoutEffect,
  Dispatch,
  SetStateAction,
} from "react";
import { cn } from "@/lib/utils";
import type { IconProps } from "@opal/types";
import { WithoutStyles } from "@/types";
import ShadowDiv from "@/refresh-components/ShadowDiv";
import {
  LineItemLayout,
  Section,
  SectionProps,
} from "@/layouts/general-layouts";
import { Card } from "@/refresh-components/cards";

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
 *   - hasContent: Whether an ActionsContent is currently mounted (read-only)
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
  const [hasContent, setHasContent] = useState(false);

  // Registration function for ActionsContent to announce its presence
  const registerContent = useMemo(
    () => () => {
      setHasContent(true);
      return () => setHasContent(false);
    },
    []
  );

  // Use a ref to hold the context value so Provider can be stable.
  // Without this, changing contextValue would create a new Provider function,
  // which React treats as a different component type, causing unmount/remount
  // of all children (and losing focus on inputs).
  const contextValueRef = useRef<ActionsLayoutContextValue>(null!);
  contextValueRef.current = {
    isFolded,
    setIsFolded,
    hasContent,
    registerContent,
  };

  // Stable Provider - reads from ref on each render, so the function
  // reference never changes but the provided value stays current.
  const Provider = useMemo(
    () =>
      ({ children }: { children: React.ReactNode }) => (
        <ActionsLayoutContext.Provider value={contextValueRef.current}>
          {children}
        </ActionsLayoutContext.Provider>
      ),
    []
  );

  return { Provider, isFolded, setIsFolded, hasContent };
}

/**
 * Actions Layout Context
 *
 * Provides folding state management for action cards without prop drilling.
 * Also tracks whether content is present via self-registration.
 */
interface ActionsLayoutContextValue {
  isFolded: boolean;
  setIsFolded: Dispatch<SetStateAction<boolean>>;
  hasContent: boolean;
  registerContent: () => () => void;
}
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
function ActionsRoot(props: SectionProps) {
  return <Section gap={0} padding={0} {...props} />;
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
export interface ActionsHeaderProps
  extends WithoutStyles<HtmlHTMLAttributes<HTMLDivElement>> {
  // Core content
  name?: string;
  title: string;
  description: string;
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
  const { isFolded, hasContent } = useActionsLayoutContext();

  // Round all corners if there's no content, or if content exists but is folded
  const shouldFullyRound = !hasContent || isFolded;

  return (
    <div
      className={cn(
        "flex flex-col border bg-background-neutral-00 w-full gap-2 pt-4 pb-2",
        shouldFullyRound ? "rounded-16" : "rounded-t-16"
      )}
    >
      <label className="px-4 cursor-pointer" htmlFor={name}>
        <LineItemLayout
          icon={Icon}
          title={title}
          description={description}
          rightChildren={rightChildren}
        />
      </label>
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
 * IMPORTANT: Only ONE ActionsContent should be used within a single ActionsRoot.
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
function ActionsContent(
  props: WithoutStyles<React.HTMLAttributes<HTMLDivElement>>
) {
  const { isFolded, registerContent } = useActionsLayoutContext();

  // Self-register with context to inform Header that content exists
  useLayoutEffect(() => {
    return registerContent();
  }, [registerContent]);

  if (isFolded) {
    return null;
  }

  return (
    <div className="border-x border-b rounded-b-16 overflow-hidden w-full">
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
  icon,
  rightChildren,
  disabled,
}: ActionsToolProps) {
  return (
    <Card padding={0.75}>
      <label className="w-full cursor-pointer" htmlFor={name}>
        <LineItemLayout
          icon={icon}
          title={title}
          description={description}
          rightChildren={rightChildren}
          strikethrough={disabled}
          variant="secondary"
        />
      </label>
    </Card>
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
  return Array.from({ length: 3 }).map((_, index) => (
    <Card key={index} padding={1.5}>
      <LineItemLayout
        // We provide dummy values here.
        // The `loading` prop will always render a pulsing box instead, so the dummy-values will actually NOT be rendered at all.
        title="..."
        description="..."
        rightChildren={<></>}
        loading
      />
    </Card>
  ));
}

export {
  ActionsRoot as Root,
  ActionsHeader as Header,
  ActionsContent as Content,
  ActionsTool as Tool,
  ActionsToolSkeleton as ToolSkeleton,
};
