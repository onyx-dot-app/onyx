"use client";

import React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { cn } from "@opal/utils";
import type {
  IconFunctionComponent,
  RichStr,
  WithoutStyles,
} from "@opal/types";
import { Button } from "@opal/components";
import { Content, Section, type SectionProps } from "@opal/layouts";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import { SvgX } from "@opal/icons";

// ---------------------------------------------------------------------------
// Root + Overlay
// ---------------------------------------------------------------------------

const ModalRoot = DialogPrimitive.Root;

const ModalOverlay = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Overlay>,
  WithoutStyles<React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>>
>(({ ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      "fixed inset-0 z-modal-overlay bg-mask-03 backdrop-blur-03 pointer-events-none",
      "data-[state=open]:animate-in data-[state=closed]:animate-out",
      "data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0"
    )}
    {...props}
  />
));
ModalOverlay.displayName = DialogPrimitive.Overlay.displayName;

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

const widthClasses = {
  full: "w-[80dvw]",
  xl: "w-240",
  lg: "w-200",
  md: "w-160",
  sm: "w-120",
};

const heightClasses = {
  fit: "h-fit",
  sm: "max-h-120 overflow-y-auto",
  lg: "max-h-[calc(100dvh-4rem)] overflow-y-auto",
  full: "h-[80dvh] overflow-y-auto",
};

// ---------------------------------------------------------------------------
// Content
// ---------------------------------------------------------------------------

interface ModalContentProps extends WithoutStyles<
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
> {
  width?: keyof typeof widthClasses;
  height?: keyof typeof heightClasses;

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

const ModalContent = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Content>,
  ModalContentProps
>(
  (
    {
      children,
      width = "xl",
      height = "fit",
      position = "center",
      preventAccidentalClose = true,
      skipOverlay = false,
      background = "default",
      bottomSlot,
      ...props
    },
    ref
  ) => {
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

    const handleRef = (node: HTMLDivElement | null) => {
      if (typeof ref === "function") {
        ref(node);
      } else if (ref) {
        ref.current = node;
      }
      contentRef(node);
    };

    const isTop = position === "top";

    const animationClasses = cn(
      "data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0",
      "data-[state=open]:zoom-in-95 data-[state=closed]:zoom-out-95",
      !isTop &&
        "data-[state=open]:slide-in-from-top-1/2 data-[state=closed]:slide-out-to-top-1/2",
      "duration-200"
    );

    const positionClasses = cn(
      "fixed -translate-x-1/2 left-1/2",
      isTop ? "top-[72px]" : "-translate-y-1/2 top-1/2"
    );

    const dialogEventHandlers = {
      onOpenAutoFocus: (e: Event) => {
        resetState();
        props.onOpenAutoFocus?.(e);
      },
      onCloseAutoFocus: (e: Event) => {
        resetState();
        props.onCloseAutoFocus?.(e);
      },
      onEscapeKeyDown: handleInteractOutside,
      onPointerDownOutside: handleInteractOutside,
      ...(!hasDescription && { "aria-describedby": undefined }),
      ...props,
    };

    const cardClasses = cn(
      "overflow-hidden",
      background === "gray" ? "bg-background-tint-01" : "bg-background-tint-00",
      "border rounded-16 shadow-2xl",
      "flex flex-col",
      heightClasses[height]
    );

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
                className={cn(
                  positionClasses,
                  "z-modal",
                  "flex flex-col gap-4 items-center",
                  "max-w-[calc(100dvw-2rem)] max-h-[calc(100dvh-2rem)]",
                  animationClasses,
                  widthClasses[width]
                )}
              >
                <div className={cn(cardClasses, "w-full min-h-0")}>
                  {children}
                </div>
                <div className="w-full shrink-0">{bottomSlot}</div>
              </div>
            </DialogPrimitive.Content>
          ) : (
            <DialogPrimitive.Content
              ref={handleRef}
              className={cn(
                positionClasses,
                "overflow-hidden",
                "z-modal",
                background === "gray"
                  ? "bg-background-tint-01"
                  : "bg-background-tint-00",
                "border rounded-16 shadow-2xl",
                "flex flex-col",
                "max-w-[calc(100dvw-2rem)] max-h-[calc(100dvh-2rem)]",
                animationClasses,
                widthClasses[width],
                heightClasses[height]
              )}
              {...dialogEventHandlers}
            >
              {children}
            </DialogPrimitive.Content>
          )}
        </DialogPrimitive.Portal>
      </ModalContext.Provider>
    );
  }
);
ModalContent.displayName = DialogPrimitive.Content.displayName;

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

/**
 * Header with icon, title, description, and close button (Figma
 * Modal/Header). Omitting `icon` yields the icon-less minimal variant.
 * `children` render below the title stack (e.g. a search input).
 */
interface ModalHeaderProps extends Omit<WithoutStyles<SectionProps>, "title"> {
  icon?: IconFunctionComponent;
  moreIcon1?: IconFunctionComponent;
  moreIcon2?: IconFunctionComponent;
  title: string | RichStr;
  description?: string | RichStr;
  onClose?: () => void;
}

const ModalHeader = React.forwardRef<HTMLDivElement, ModalHeaderProps>(
  (
    {
      icon,
      moreIcon1,
      moreIcon2,
      title,
      description,
      onClose,
      children,
      ...props
    },
    ref
  ) => {
    const { closeButtonRef, setHasDescription } = useModalContext();

    React.useLayoutEffect(() => {
      setHasDescription(!!description);
    }, [description, setHasDescription]);

    const closeButton = onClose && (
      <div
        tabIndex={-1}
        ref={closeButtonRef as React.RefObject<HTMLDivElement>}
        className="outline-hidden"
      >
        <DialogPrimitive.Close asChild>
          <Button
            icon={SvgX}
            prominence="tertiary"
            size="sm"
            onClick={onClose}
          />
        </DialogPrimitive.Close>
      </div>
    );

    return (
      <Section
        ref={ref}
        padding={0.5}
        alignItems="start"
        height="fit"
        {...props}
      >
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="start"
          gap={0}
          padding={0.5}
        >
          <div className="relative w-full">
            {/* Absolutely positioned per the Figma mocks: the close button
               overlaps the content's top-right so the description keeps the
               full width. */}
            <div className="absolute top-0 right-0">{closeButton}</div>
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
                  <DialogPrimitive.Description className="hidden">
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
);
ModalHeader.displayName = "ModalHeader";

// ---------------------------------------------------------------------------
// Body + Footer
// ---------------------------------------------------------------------------

interface ModalBodyProps extends WithoutStyles<SectionProps> {
  /** Gray body background separating it from the header/footer. */
  twoTone?: boolean;
}

const ModalBody = React.forwardRef<HTMLDivElement, ModalBodyProps>(
  ({ twoTone = true, children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          twoTone && "bg-background-tint-01",
          "flex-auto min-h-0 overflow-y-auto w-full"
        )}
      >
        <Section
          height="auto"
          padding={1}
          gap={1}
          alignItems="start"
          {...props}
        >
          {children}
        </Section>
      </div>
    );
  }
);
ModalBody.displayName = "ModalBody";

const ModalFooter = React.forwardRef<
  HTMLDivElement,
  WithoutStyles<SectionProps>
>(({ ...props }, ref) => {
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
});
ModalFooter.displayName = "ModalFooter";

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
