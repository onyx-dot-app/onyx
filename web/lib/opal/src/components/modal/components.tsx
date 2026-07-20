"use client";

import "@opal/components/modal/styles.css";

import React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import type {
  IconFunctionComponent,
  RichStr,
  SizeVariants,
  WithoutStyles,
} from "@opal/types";
import { Button } from "@opal/components";
import { Content, Section, type SectionProps } from "@opal/layouts";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import { SvgX } from "@opal/icons";
import useContainerCenter from "@opal/hooks/useContainerCenter";

// ---------------------------------------------------------------------------
// Root + Overlay
// ---------------------------------------------------------------------------

const ModalRoot = DialogPrimitive.Root;

interface ModalOverlayProps extends WithoutStyles<
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
> {
  ref?: React.Ref<React.ComponentRef<typeof DialogPrimitive.Overlay>>;
}

function ModalOverlay({ ref, ...props }: ModalOverlayProps) {
  return (
    <DialogPrimitive.Overlay
      ref={ref}
      className="opal-modal-overlay"
      {...props}
    />
  );
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

// Shared by Content and Header: the close-button ref receives focus on a
// guarded close attempt, and setHasDescription drives aria-describedby.
interface ModalContextValue {
  closeButtonRef: React.RefObject<HTMLDivElement | null>;
  setHasDescription: (value: boolean) => void;
}

const ModalContext = React.createContext<ModalContextValue | null>(null);

const useModalContext = () => {
  const context = React.useContext(ModalContext);
  if (!context) {
    throw new Error("Modal compound components must be used within Modal");
  }
  return context;
};

type ModalWidth = Extract<SizeVariants, "sm" | "md" | "lg" | "xl" | "full">;
type ModalHeight = Extract<SizeVariants, "fit" | "sm" | "lg" | "full">;

// ---------------------------------------------------------------------------
// Content
// ---------------------------------------------------------------------------

interface ModalContentProps extends WithoutStyles<
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
> {
  ref?: React.Ref<React.ComponentRef<typeof DialogPrimitive.Content>>;

  width?: ModalWidth;
  height?: ModalHeight;

  /**
   * Vertical placement. `"center"` (default) centers in the viewport.
   * `"top"` pins the modal near the top, the command-menu position.
   */
  position?: "center" | "top";

  /**
   * Two-stage close guard: once the user has typed into any text input in
   * the modal, the first Escape/outside-click focuses the close button
   * instead of closing, and the second closes.
   */
  preventAccidentalClose?: boolean;

  skipOverlay?: boolean;

  background?: "default" | "gray";

  /**
   * Content rendered below the modal card with 1rem separation. Stays inside
   * DialogPrimitive.Content so focus management covers it.
   */
  bottomSlot?: React.ReactNode;
}

function ModalContent({
  ref,
  children,
  width = "xl",
  height = "fit",
  position = "center",
  preventAccidentalClose = true,
  skipOverlay = false,
  background = "default",
  bottomSlot,
  ...props
}: ModalContentProps) {
  const closeButtonRef = React.useRef<HTMLDivElement>(null);
  const [hasAttemptedClose, setHasAttemptedClose] = React.useState(false);
  const [hasDescription, setHasDescription] = React.useState(false);
  const hasUserTypedRef = React.useRef(false);

  const resetState = React.useCallback(() => {
    setHasAttemptedClose(false);
    hasUserTypedRef.current = false;
  }, []);

  // Trusted input events on text fields mark the modal dirty for the
  // accidental-close guard.
  const handleInput = React.useCallback((e: Event) => {
    if (hasUserTypedRef.current) return;
    if (!e.isTrusted) return;

    const target = e.target as HTMLElement;
    if (
      !(
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement
      )
    ) {
      return;
    }
    if (
      target.type === "hidden" ||
      target.type === "submit" ||
      target.type === "button" ||
      target.type === "checkbox" ||
      target.type === "radio"
    ) {
      return;
    }
    hasUserTypedRef.current = true;
  }, []);

  const containerNodeRef = React.useRef<HTMLDivElement | null>(null);

  const contentRef = React.useCallback(
    (node: HTMLDivElement | null) => {
      if (containerNodeRef.current) {
        containerNodeRef.current.removeEventListener(
          "input",
          handleInput,
          true
        );
      }
      if (node) {
        node.addEventListener("input", handleInput, true);
        containerNodeRef.current = node;
      } else {
        containerNodeRef.current = null;
      }
    },
    [handleInput]
  );

  const handleInteractOutside = React.useCallback(
    (e: Event) => {
      if (!preventAccidentalClose) {
        setHasAttemptedClose(false);
        return;
      }
      if (hasUserTypedRef.current) {
        if (!hasAttemptedClose) {
          e.preventDefault();
          setHasAttemptedClose(true);
          setTimeout(() => {
            closeButtonRef.current?.focus();
          }, 0);
        } else {
          setHasAttemptedClose(false);
        }
      } else {
        setHasAttemptedClose(false);
      }
    },
    [preventAccidentalClose, hasAttemptedClose]
  );

  const handleRef = React.useCallback(
    (node: HTMLDivElement | null) => {
      if (typeof ref === "function") {
        ref(node);
      } else if (ref) {
        ref.current = node;
      }
      contentRef(node);
    },
    [ref, contentRef]
  );

  // Center on [data-main-container] when present (the content area beside
  // the sidebar) instead of the viewport.
  const { centerX, centerY, hasContainerCenter } = useContainerCenter();

  const isTop = position === "top";

  const containerStyle: React.CSSProperties | undefined =
    hasContainerCenter && !isTop
      ? ({
          left: centerX,
          top: centerY,
          "--tw-enter-translate-x": "-50%",
          "--tw-exit-translate-x": "-50%",
          "--tw-enter-translate-y": "-50%",
          "--tw-exit-translate-y": "-50%",
        } as React.CSSProperties)
      : hasContainerCenter && isTop
        ? ({
            left: centerX,
            "--tw-enter-translate-x": "-50%",
            "--tw-exit-translate-x": "-50%",
          } as React.CSSProperties)
        : undefined;

  const positionerData = {
    "data-position": position,
    "data-width": width,
    ...(!hasContainerCenter && { "data-viewport-centered": "" }),
  };

  // Internal handlers are defined after the props spread so callers cannot
  // replace them. Each forwards to the caller's handler.
  const dialogEventHandlers = {
    ...(!hasDescription && { "aria-describedby": undefined }),
    ...props,
    onOpenAutoFocus: (e: Event) => {
      resetState();
      props.onOpenAutoFocus?.(e);
    },
    onCloseAutoFocus: (e: Event) => {
      resetState();
      props.onCloseAutoFocus?.(e);
    },
    onEscapeKeyDown: (e: KeyboardEvent) => {
      handleInteractOutside(e);
      props.onEscapeKeyDown?.(e);
    },
    onPointerDownOutside: (
      e: Parameters<
        NonNullable<
          React.ComponentPropsWithoutRef<
            typeof DialogPrimitive.Content
          >["onPointerDownOutside"]
        >
      >[0]
    ) => {
      handleInteractOutside(e);
      props.onPointerDownOutside?.(e);
    },
  };

  return (
    <ModalContext.Provider
      value={{
        closeButtonRef,
        setHasDescription,
      }}
    >
      <DialogPrimitive.Portal>
        {!skipOverlay && <ModalOverlay />}
        {bottomSlot ? (
          <DialogPrimitive.Content
            asChild
            ref={handleRef}
            {...dialogEventHandlers}
          >
            <div
              style={containerStyle}
              className="opal-modal-positioner opal-modal-stack"
              {...positionerData}
            >
              <div
                className="opal-modal-card"
                data-height={height}
                data-background={background}
              >
                {children}
              </div>
              <div className="opal-modal-bottom-slot">{bottomSlot}</div>
            </div>
          </DialogPrimitive.Content>
        ) : (
          <DialogPrimitive.Content
            ref={handleRef}
            style={containerStyle}
            className="opal-modal-positioner opal-modal-card"
            data-height={height}
            data-background={background}
            {...positionerData}
            {...dialogEventHandlers}
          >
            {children}
          </DialogPrimitive.Content>
        )}
      </DialogPrimitive.Portal>
    </ModalContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

/**
 * Header with icon, title, description, and close button (Figma
 * Modal/Header). Omitting `icon` yields the icon-less minimal variant.
 * `children` render below the title stack (e.g. a search input).
 */
interface ModalHeaderProps extends Omit<WithoutStyles<SectionProps>, "title"> {
  ref?: React.Ref<HTMLDivElement>;
  icon?: IconFunctionComponent;
  moreIcon1?: IconFunctionComponent;
  moreIcon2?: IconFunctionComponent;
  title: string | RichStr;
  description?: string | RichStr;
  onClose?: () => void;
}

function ModalHeader({
  ref,
  icon,
  moreIcon1,
  moreIcon2,
  title,
  description,
  onClose,
  children,
  ...props
}: ModalHeaderProps) {
  const { closeButtonRef, setHasDescription } = useModalContext();

  React.useLayoutEffect(() => {
    setHasDescription(!!description);
  }, [description, setHasDescription]);

  const closeButton = onClose && (
    <div
      tabIndex={-1}
      ref={closeButtonRef as React.RefObject<HTMLDivElement>}
      className="opal-modal-close-focus"
    >
      <DialogPrimitive.Close asChild>
        <Button icon={SvgX} prominence="tertiary" size="sm" onClick={onClose} />
      </DialogPrimitive.Close>
    </div>
  );

  return (
    <Section ref={ref} padding={0.5} alignItems="start" height="fit" {...props}>
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="start"
        gap={0}
        padding={0.5}
      >
        <div className="opal-modal-header-content">
          <div className="opal-modal-header-close">{closeButton}</div>
          <DialogPrimitive.Title asChild>
            <div>
              <Content
                icon={icon}
                moreIcon1={moreIcon1}
                moreIcon2={moreIcon2}
                title={title}
                description={description}
                sizePreset="section"
                variant="heading"
              />
              {description && (
                <DialogPrimitive.Description className="opal-modal-a11y-description">
                  {toPlainString(description)}
                </DialogPrimitive.Description>
              )}
            </div>
          </DialogPrimitive.Title>
        </div>
      </Section>
      {children}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Body + Footer
// ---------------------------------------------------------------------------

interface ModalBodyProps extends WithoutStyles<SectionProps> {
  ref?: React.Ref<HTMLDivElement>;
  /** Gray body background separating it from the header/footer. */
  twoTone?: boolean;
}

function ModalBody({
  ref,
  twoTone = true,
  children,
  ...props
}: ModalBodyProps) {
  return (
    <div
      ref={ref}
      className="opal-modal-body"
      {...(twoTone && { "data-two-tone": "" })}
    >
      <Section height="auto" padding={1} gap={1} alignItems="start" {...props}>
        {children}
      </Section>
    </div>
  );
}

interface ModalFooterProps extends WithoutStyles<SectionProps> {
  ref?: React.Ref<HTMLDivElement>;
}

function ModalFooter({ ref, ...props }: ModalFooterProps) {
  return (
    <Section
      ref={ref}
      flexDirection="row"
      justifyContent="end"
      gap={0.5}
      padding={1}
      height="fit"
      {...props}
    />
  );
}

/**
 * Modal (Figma Modal): Radix Dialog compound. `Modal` is the Radix root
 * (`open`/`onOpenChange`). Content renders the scrim, positioning, and
 * card. Header/Body/Footer are the card's sections.
 */
const Modal = Object.assign(ModalRoot, {
  Content: ModalContent,
  Header: ModalHeader,
  Body: ModalBody,
  Footer: ModalFooter,
});

// ---------------------------------------------------------------------------
// Common layouts
// ---------------------------------------------------------------------------

interface BasicModalFooterProps {
  left?: React.ReactNode;
  cancel?: React.ReactNode;
  submit?: React.ReactNode;
}

/** Footer layout with an optional left slot and right-aligned cancel/submit. */
function BasicModalFooter({ left, cancel, submit }: BasicModalFooterProps) {
  return (
    <>
      {left && <Section alignItems="start">{left}</Section>}
      {(cancel || submit) && (
        <Section flexDirection="row" justifyContent="end" gap={0.5}>
          {cancel}
          {submit}
        </Section>
      )}
    </>
  );
}

export {
  Modal,
  BasicModalFooter,
  type ModalContentProps,
  type ModalHeaderProps,
  type ModalBodyProps,
  type BasicModalFooterProps,
};
