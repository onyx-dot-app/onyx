"use client";

import "@opal/components/collapsible/styles.css";
import { createContext, useContext, useId, useState } from "react";
import { Slot } from "@radix-ui/react-slot";
import type { RichStr, Spacing } from "@opal/types";
import { spacingToRem } from "@opal/shared";
import { ContentAction, Section } from "@opal/layouts";
import { Button, type TagProps } from "@opal/components";
import { Fold } from "@opal/components/fold/components";
import { SvgExpand, SvgFold } from "@opal/icons";
import { useOpalStrings } from "@opal/strings";
import { toPlainString } from "@opal/components/text/InlineMarkdown";

interface CollapsibleProps {
  title: string | RichStr;
  description?: string | RichStr;
  /** Tag shown next to the title. */
  tag?: TagProps;
  /** Controlled open state. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Initial open state when uncontrolled. */
  defaultOpen?: boolean;
  /** Locks the current open state: clicks and keys do not toggle. */
  disabled?: boolean;
  /** Controls before the fold button, such as an edit action. Clicks there do not toggle. */
  rightChildren?: React.ReactNode;
  children?: React.ReactNode;
}

/**
 * A titled section: a header with a title, description and fold button, over
 * a body that opens and closes. It is a preset of the composable parts below:
 * the state of `Collapsible.Root`, and a body that is a `Collapsible.Content`
 * with `paddingTop={3}`.
 */
function CollapsibleSection({
  defaultOpen = true,
  open,
  onOpenChange,
  disabled = false,
  ...props
}: CollapsibleProps) {
  // No root element: the layout's own element is the section's root, so it
  // fills the width of a flex parent.
  return (
    <CollapsibleProvider
      open={open}
      onOpenChange={onOpenChange}
      defaultOpen={defaultOpen}
      disabled={disabled}
    >
      <CollapsibleSectionLayout disabled={disabled} {...props} />
    </CollapsibleProvider>
  );
}

type CollapsibleSectionLayoutProps = Omit<
  CollapsibleProps,
  "open" | "onOpenChange" | "defaultOpen"
>;

/** The section's header and body, reading the state from its root. */
function CollapsibleSectionLayout({
  title,
  description,
  tag,
  disabled = false,
  rightChildren,
  children,
}: CollapsibleSectionLayoutProps) {
  const strings = useOpalStrings();
  const { open, toggle, contentId } = useCollapsibleContext("Section");
  const [hovered, setHovered] = useState(false);
  const [focusVisible, setFocusVisible] = useState(false);
  // The body renders from the first open and then stays mounted, so a closed
  // section does no work until it is opened and later closes still animate.
  const [hasOpened, setHasOpened] = useState(open);
  if (open && !hasOpened) setHasOpened(true);

  const label = open ? strings.collapsibleFold : strings.collapsibleExpand;
  const plainTitle = toPlainString(title);
  const accessibleLabel = open
    ? strings.collapsibleFoldSection(plainTitle)
    : strings.collapsibleExpandSection(plainTitle);

  return (
    <div
      className="opal-collapsible"
      data-state={open ? "open" : "closed"}
      data-disabled={disabled || undefined}
    >
      {/* Pointer convenience only: the whole row toggles. The Button is the
          keyboard control and toggles itself, as its wrapper stops clicks. */}
      <div
        role="presentation"
        className="opal-collapsible-header"
        onClick={toggle}
        onPointerEnter={() => setHovered(true)}
        onPointerLeave={() => setHovered(false)}
      >
        <ContentAction
          title={title}
          description={description}
          tag={tag}
          sizePreset="main-content"
          variant="section"
          padding={0}
          center
          rightChildren={
            <Section
              flexDirection="row"
              width="fit"
              height="fit"
              gap={1}
              onClick={(e) => e.stopPropagation()}
            >
              {/* Its own controls, so the fold button does not light up. */}
              {rightChildren !== undefined && rightChildren !== false && (
                <Section
                  flexDirection="row"
                  width="fit"
                  height="fit"
                  gap={1}
                  onPointerEnter={() => setHovered(false)}
                  onPointerLeave={() => setHovered(true)}
                >
                  {rightChildren}
                </Section>
              )}
              {/* The one control whose keyboard focus shows as hover. */}
              <Section
                width="fit"
                height="fit"
                className="opal-collapsible-fold"
              >
                <Button
                  icon={open ? SvgFold : SvgExpand}
                  prominence="tertiary"
                  interaction={
                    !disabled && (hovered || focusVisible) ? "hover" : "rest"
                  }
                  disabled={disabled}
                  tooltip={label}
                  aria-label={accessibleLabel}
                  aria-expanded={open}
                  aria-controls={contentId}
                  onClick={toggle}
                  onFocus={(e) =>
                    setFocusVisible(e.currentTarget.matches(":focus-visible"))
                  }
                  onBlur={() => setFocusVisible(false)}
                />
              </Section>
            </Section>
          }
        />
      </div>
      <CollapsibleContent paddingTop={3} keepMounted>
        {hasOpened && children}
      </CollapsibleContent>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Composable parts
// ---------------------------------------------------------------------------

interface CollapsibleContextValue {
  open: boolean;
  /** The trigger cannot toggle, and says so. */
  disabled: boolean;
  toggle: () => void;
  contentId: string;
}

const CollapsibleContext = createContext<CollapsibleContextValue | null>(null);

function useCollapsibleContext(part: string): CollapsibleContextValue {
  const context = useContext(CollapsibleContext);
  if (!context) {
    throw new Error(`Collapsible.${part} must be inside Collapsible.Root`);
  }
  return context;
}

interface CollapsibleRootProps {
  /** Controlled open state. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Initial open state when uncontrolled. @default false */
  defaultOpen?: boolean;
  /** Locks the current open state: the trigger does not toggle. */
  disabled?: boolean;
  children?: React.ReactNode;
}

/**
 * The state of a collapsible whose header the caller draws: pair it with
 * `Collapsible.Trigger` and `Collapsible.Content`. For a titled section with
 * Opal's own header and fold button, use `Collapsible` itself.
 */
function CollapsibleRoot({ children, ...props }: CollapsibleRootProps) {
  return (
    <CollapsibleProvider {...props}>
      <CollapsibleRootElement>{children}</CollapsibleRootElement>
    </CollapsibleProvider>
  );
}

/** The root's element, with the state as data attributes. */
function CollapsibleRootElement({ children }: { children?: React.ReactNode }) {
  const { open, disabled } = useCollapsibleContext("Root");
  return (
    <div
      data-state={open ? "open" : "closed"}
      data-disabled={disabled || undefined}
    >
      {children}
    </div>
  );
}

/** The state of a collapsible, without an element of its own. */
function CollapsibleProvider({
  open: openProp,
  onOpenChange,
  defaultOpen = false,
  disabled = false,
  children,
}: CollapsibleRootProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const open = openProp ?? uncontrolledOpen;
  const contentId = useId();

  function toggle() {
    if (disabled) return;
    const next = !open;
    if (openProp === undefined) setUncontrolledOpen(next);
    onOpenChange?.(next);
  }

  return (
    <CollapsibleContext.Provider value={{ open, disabled, toggle, contentId }}>
      {children}
    </CollapsibleContext.Provider>
  );
}

type CollapsibleTriggerProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  /** Toggles through the child element instead of a `<button>`. */
  asChild?: boolean;
};

/** Toggles the nearest `Collapsible.Root`. */
function CollapsibleTrigger({
  asChild = false,
  onClick,
  onClickCapture,
  ...props
}: CollapsibleTriggerProps) {
  const { open, disabled, toggle, contentId } =
    useCollapsibleContext("Trigger");
  const Component = asChild ? Slot : "button";
  return (
    <Component
      // A native trigger is disabled; another element says so, since it
      // has no `disabled` of its own.
      {...(asChild
        ? { "aria-disabled": disabled || undefined }
        : { type: "button" as const, disabled })}
      {...props}
      aria-expanded={open}
      aria-controls={contentId}
      data-state={open ? "open" : "closed"}
      data-disabled={disabled || undefined}
      // A disabled native button gets no clicks. Another element does, so
      // the click stops here, before any handler on it or its child runs.
      onClickCapture={(event: React.MouseEvent<HTMLButtonElement>) => {
        if (disabled) {
          event.preventDefault();
          event.stopPropagation();
          return;
        }
        onClickCapture?.(event);
      }}
      onClick={(event: React.MouseEvent<HTMLButtonElement>) => {
        if (disabled) return;
        onClick?.(event);
        if (!event.defaultPrevented) toggle();
      }}
    />
  );
}

interface CollapsibleContentProps {
  /**
   * Space above the content, as a spacing step (`N / 4` rem). It is inside
   * the part that animates, so it opens and closes with the content.
   * @default 0
   */
  paddingTop?: Spacing;
  /** Keep the children while closed. Off, they drop once it closes. */
  keepMounted?: boolean;
  children?: React.ReactNode;
}

/** The part that opens and closes, with Opal's fold animation. */
function CollapsibleContent({
  paddingTop = 0,
  keepMounted,
  children,
}: CollapsibleContentProps) {
  const { open, contentId } = useCollapsibleContext("Content");
  return (
    <Fold open={open} keepMounted={keepMounted} id={contentId}>
      <div style={{ paddingTop: spacingToRem(paddingTop) }}>{children}</div>
    </Fold>
  );
}

const Collapsible = Object.assign(CollapsibleSection, {
  Root: CollapsibleRoot,
  Trigger: CollapsibleTrigger,
  Content: CollapsibleContent,
});

export {
  Collapsible,
  type CollapsibleProps,
  type CollapsibleRootProps,
  type CollapsibleTriggerProps,
  type CollapsibleContentProps,
};
