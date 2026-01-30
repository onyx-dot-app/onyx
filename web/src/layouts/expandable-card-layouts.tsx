/**
 * Expandable Card Layout Components
 *
 * A namespaced collection of components for building expandable cards with
 * collapsible content sections. These provide the structural foundation
 * without opinionated content styling - just pure containers.
 *
 * Use these components when you need:
 * - A card with a header that can have expandable content below it
 * - Automatic border-radius handling based on whether content exists/is folded
 * - Controlled or uncontrolled folding state
 *
 * @example
 * ```tsx
 * import * as ExpandableCard from "@/layouts/expandable-card-layouts";
 *
 * // Uncontrolled — Root manages its own state
 * function MyCard() {
 *   return (
 *     <ExpandableCard.Root>
 *       <ExpandableCard.Header>
 *         <div className="p-4">
 *           <h3>My Header</h3>
 *         </div>
 *       </ExpandableCard.Header>
 *       <ExpandableCard.Content>
 *         <div className="p-4">
 *           <p>Expandable content goes here</p>
 *         </div>
 *       </ExpandableCard.Content>
 *     </ExpandableCard.Root>
 *   );
 * }
 *
 * // Controlled — consumer owns the state
 * function MyControlledCard() {
 *   const [isFolded, setIsFolded] = useState(false);
 *
 *   return (
 *     <ExpandableCard.Root isFolded={isFolded} onFoldedChange={setIsFolded}>
 *       <ExpandableCard.Header>
 *         <button onClick={() => setIsFolded(!isFolded)}>Toggle</button>
 *       </ExpandableCard.Header>
 *       <ExpandableCard.Content>
 *         <p>Content here</p>
 *       </ExpandableCard.Content>
 *     </ExpandableCard.Root>
 *   );
 * }
 * ```
 */

"use client";

import React, {
  createContext,
  useContext,
  useState,
  useMemo,
  useLayoutEffect,
  Dispatch,
  SetStateAction,
} from "react";
import { cn } from "@/lib/utils";
import { WithoutStyles } from "@/types";
import ShadowDiv from "@/refresh-components/ShadowDiv";
import { Section, SectionProps } from "@/layouts/general-layouts";
import {
  Collapsible,
  CollapsibleContent,
} from "@/refresh-components/Collapsible";

/**
 * Expandable Card Context
 *
 * Provides folding state management for expandable cards without prop drilling.
 * Also tracks whether content is present via self-registration.
 */
interface ExpandableCardContextValue {
  isFolded: boolean;
  setIsFolded: Dispatch<SetStateAction<boolean>>;
  hasContent: boolean;
  registerContent: () => () => void;
}

const ExpandableCardContext = createContext<
  ExpandableCardContextValue | undefined
>(undefined);

function useExpandableCardContext() {
  const context = useContext(ExpandableCardContext);
  if (!context) {
    throw new Error(
      "ExpandableCard components must be used within an ExpandableCard.Root"
    );
  }
  return context;
}

/**
 * Expandable Card Root Component
 *
 * The root container and context provider for an expandable card. Provides a
 * flex column layout with no gap or padding by default.
 *
 * Supports both controlled and uncontrolled folding state:
 * - **Uncontrolled**: Manages its own state. Use `defaultFolded` to set the
 *   initial folding state (defaults to `false`, i.e. expanded).
 * - **Controlled**: Pass `isFolded` and `onFoldedChange` to manage folding
 *   state externally.
 *
 * @example
 * ```tsx
 * // Uncontrolled
 * <ExpandableCard.Root>
 *   <ExpandableCard.Header>...</ExpandableCard.Header>
 *   <ExpandableCard.Content>...</ExpandableCard.Content>
 * </ExpandableCard.Root>
 *
 * // Uncontrolled, starts folded
 * <ExpandableCard.Root defaultFolded>
 *   ...
 * </ExpandableCard.Root>
 *
 * // Controlled
 * const [isFolded, setIsFolded] = useState(false);
 * <ExpandableCard.Root isFolded={isFolded} onFoldedChange={setIsFolded}>
 *   ...
 * </ExpandableCard.Root>
 * ```
 */
export interface ExpandableCardRootProps extends SectionProps {
  /** Controlled folding state. When provided, the component is controlled. */
  isFolded?: boolean;
  /** Callback when folding state changes. Required for controlled usage. */
  onFoldedChange?: Dispatch<SetStateAction<boolean>>;
  /** Initial folding state for uncontrolled usage. Defaults to `false`. */
  defaultFolded?: boolean;
}

function ExpandableCardRoot({
  isFolded: controlledFolded,
  onFoldedChange,
  defaultFolded = false,
  ...props
}: ExpandableCardRootProps) {
  const [uncontrolledFolded, setUncontrolledFolded] = useState(defaultFolded);
  const isControlled = controlledFolded !== undefined;
  const isFolded = isControlled ? controlledFolded : uncontrolledFolded;
  const setIsFolded = isControlled
    ? onFoldedChange ?? (() => {})
    : setUncontrolledFolded;

  const [hasContent, setHasContent] = useState(false);

  // Registration function for Content to announce its presence
  const registerContent = useMemo(
    () => () => {
      setHasContent(true);
      return () => setHasContent(false);
    },
    []
  );

  const contextValue = useMemo(
    () => ({ isFolded, setIsFolded, hasContent, registerContent }),
    [isFolded, setIsFolded, hasContent, registerContent]
  );

  return (
    <ExpandableCardContext.Provider value={contextValue}>
      <Section gap={0} padding={0} {...props} />
    </ExpandableCardContext.Provider>
  );
}

/**
 * Expandable Card Header Component
 *
 * The header section of an expandable card. This is a pure container that:
 * - Has a border and neutral background
 * - Automatically handles border-radius based on content state:
 *   - Fully rounded when no content exists or when content is folded
 *   - Only top-rounded when content is visible
 *
 * You are responsible for adding your own padding, layout, and content inside.
 *
 * @example
 * ```tsx
 * <ExpandableCard.Header>
 *   <div className="flex items-center justify-between p-4">
 *     <h3>My Title</h3>
 *     <button>Action</button>
 *   </div>
 * </ExpandableCard.Header>
 * ```
 */
export interface ExpandableCardHeaderProps
  extends WithoutStyles<React.HTMLAttributes<HTMLDivElement>> {
  children?: React.ReactNode;
}

function ExpandableCardHeader({
  children,
  ...props
}: ExpandableCardHeaderProps) {
  const { isFolded, hasContent } = useExpandableCardContext();

  // Round all corners if there's no content, or if content exists but is folded
  const shouldFullyRound = !hasContent || isFolded;

  return (
    <div
      {...props}
      className={cn(
        "border bg-background-neutral-00 w-full transition-[border-radius] duration-200 ease-out",
        shouldFullyRound ? "rounded-16" : "rounded-t-16"
      )}
    >
      {children}
    </div>
  );
}

/**
 * Expandable Card Content Component
 *
 * The expandable content section of the card. This is a pure container that:
 * - Self-registers with context to inform Header about its presence
 * - Animates open/closed using Radix Collapsible (slide down/up)
 * - Has side and bottom borders that connect to the header
 * - Has a max-height with scrollable overflow via ShadowDiv
 *
 * You are responsible for adding your own content inside.
 *
 * IMPORTANT: Only ONE Content component should be used within a single Root.
 * This component self-registers with the context to inform Header whether
 * content exists (for border-radius styling). Using multiple Content components
 * will cause incorrect unmount behavior.
 *
 * @example
 * ```tsx
 * <ExpandableCard.Content>
 *   <div className="p-4">
 *     <p>Your expandable content here</p>
 *   </div>
 * </ExpandableCard.Content>
 * ```
 */
export interface ExpandableCardContentProps
  extends WithoutStyles<React.HTMLAttributes<HTMLDivElement>> {
  children?: React.ReactNode;
}

function ExpandableCardContent({
  children,
  ...props
}: ExpandableCardContentProps) {
  const { isFolded, registerContent } = useExpandableCardContext();

  // Self-register with context to inform Header that content exists
  useLayoutEffect(() => {
    return registerContent();
  }, [registerContent]);

  return (
    <Collapsible open={!isFolded}>
      <CollapsibleContent>
        <div
          className={cn(
            "border-x border-b rounded-b-16 overflow-hidden w-full transition-opacity duration-200 ease-out",
            isFolded ? "opacity-0" : "opacity-100"
          )}
        >
          <ShadowDiv
            className="flex flex-col rounded-b-16 max-h-[20rem]"
            {...props}
          >
            {children}
          </ShadowDiv>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

export {
  ExpandableCardRoot as Root,
  ExpandableCardHeader as Header,
  ExpandableCardContent as Content,
};
