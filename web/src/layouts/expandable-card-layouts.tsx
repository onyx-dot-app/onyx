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
 * function MyCard() {
 *   const { Provider, isFolded, setIsFolded } = ExpandableCard.useExpandableCard();
 *
 *   return (
 *     <Provider>
 *       <ExpandableCard.Root>
 *         <ExpandableCard.Header>
 *           <div className="p-4">
 *             <h3>My Header</h3>
 *             <button onClick={() => setIsFolded(!isFolded)}>Toggle</button>
 *           </div>
 *         </ExpandableCard.Header>
 *         <ExpandableCard.Content>
 *           <div className="p-4">
 *             <p>Expandable content goes here</p>
 *           </div>
 *         </ExpandableCard.Content>
 *       </ExpandableCard.Root>
 *     </Provider>
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
  useRef,
  useLayoutEffect,
  Dispatch,
  SetStateAction,
} from "react";
import { cn } from "@/lib/utils";
import { WithoutStyles } from "@/types";
import ShadowDiv from "@/refresh-components/ShadowDiv";
import { Section, SectionProps } from "@/layouts/general-layouts";

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
      "ExpandableCard components must be used within an ExpandableCard Provider"
    );
  }
  return context;
}

/**
 * Hook to create an ExpandableCard context provider and controller.
 *
 * @returns An object containing:
 *   - Provider: Context provider component to wrap the card
 *   - isFolded: Current folding state
 *   - setIsFolded: Function to update folding state
 *   - hasContent: Whether Content is currently mounted (read-only)
 *
 * @example
 * ```tsx
 * function MyCard() {
 *   const { Provider, isFolded, setIsFolded } = ExpandableCard.useExpandableCard();
 *
 *   return (
 *     <Provider>
 *       <ExpandableCard.Root>
 *         <ExpandableCard.Header>
 *           <button onClick={() => setIsFolded(!isFolded)}>
 *             {isFolded ? 'Expand' : 'Collapse'}
 *           </button>
 *         </ExpandableCard.Header>
 *         <ExpandableCard.Content>
 *           <p>Content here</p>
 *         </ExpandableCard.Content>
 *       </ExpandableCard.Root>
 *     </Provider>
 *   );
 * }
 * ```
 */
export function useExpandableCard() {
  const [isFolded, setIsFolded] = useState(false);
  const [hasContent, setHasContent] = useState(false);

  // Registration function for Content to announce its presence
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
  const contextValueRef = useRef<ExpandableCardContextValue>(null!);
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
        <ExpandableCardContext.Provider value={contextValueRef.current}>
          {children}
        </ExpandableCardContext.Provider>
      ),
    []
  );

  return { Provider, isFolded, setIsFolded, hasContent };
}

/**
 * Expandable Card Root Component
 *
 * The root container for an expandable card. Provides a flex column layout
 * with no gap or padding by default.
 *
 * @example
 * ```tsx
 * <ExpandableCard.Root>
 *   <ExpandableCard.Header>...</ExpandableCard.Header>
 *   <ExpandableCard.Content>...</ExpandableCard.Content>
 * </ExpandableCard.Root>
 * ```
 */
function ExpandableCardRoot(props: SectionProps) {
  return <Section gap={0} padding={0} {...props} />;
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
        "border bg-background-neutral-00 w-full",
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
 * - Renders nothing when folded
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

  if (isFolded) {
    return null;
  }

  return (
    <div className="border-x border-b rounded-b-16 overflow-hidden w-full">
      <ShadowDiv
        className="flex flex-col rounded-b-16 max-h-[20rem]"
        {...props}
      >
        {children}
      </ShadowDiv>
    </div>
  );
}

export {
  ExpandableCardRoot as Root,
  ExpandableCardHeader as Header,
  ExpandableCardContent as Content,
};
