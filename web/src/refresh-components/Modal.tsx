"use client";

import React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { cn } from "@/lib/utils";
import type { IconProps } from "@opal/types";
import Text from "@/refresh-components/texts/Text";
import { Button } from "@opal/components";
import { SvgX } from "@opal/icons";
import { WithoutStyles } from "@/types";
import { Section, SectionProps } from "@/layouts/general-layouts";
import useContainerCenter from "@/hooks/useContainerCenter";

/**
 * Modal Root Component
 *
 * Wrapper around Radix Dialog.Root for managing modal state.
 *
 * @example
 * ```tsx
 * <Modal open={isOpen} onOpenChange={setIsOpen}>
 *   <Modal.Content>
 *     {/* Modal content *\/}
 *   </Modal.Content>
 * </Modal>
 * ```
 */
const ModalRoot = DialogPrimitive.Root;

/**
 * Modal Overlay Component
 *
 * Backdrop overlay that appears behind the modal.
 *
 * @example
 * ```tsx
 * <Modal.Overlay />
 * ```
 */
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

/**
 * Modal Context for managing close button ref, warning state, and height variant
 */
interface ModalContextValue {
  closeButtonRef: React.RefObject<HTMLDivElement | null>;
  hasAttemptedClose: boolean;
  setHasAttemptedClose: (value: boolean) => void;
  height: keyof typeof heightClasses;
  hasDescription: boolean;
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
  lg: "w-[80dvw]",
  md: "w-[60rem]",
  "md-sm": "w-[50rem]",
  sm: "w-[32rem]",
};

const heightClasses = {
  fit: "h-fit",
  sm: "max-h-[30rem] overflow-y-auto",
  lg: "max-h-[calc(100dvh-4rem)] overflow-y-auto",
  full: "h-[80dvh] overflow-y-auto",
};

/**
 * Modal Content Component
 *
 * Main modal container with default styling.
 *
 * @example
 * ```tsx
 * // Using width and height props
 * <Modal.Content width="lg" height="full">
 *   {/* Large modal: w-[80dvw] h-[80dvh] *\/}
 * </Modal.Content>
 *
 * <Modal.Content width="md" height="fit">
 *   {/* Medium modal: w-[60rem] h-fit *\/}
 * </Modal.Content>
 *
 * <Modal.Content width="sm" height="sm">
 *   {/* Small modal: w-[32rem] max-h-[30rem] *\/}
 * </Modal.Content>
 *
 * <Modal.Content width="sm" height="lg">
 *   {/* Tall modal: w-[32rem] max-h-[calc(100dvh-4rem)] *\/}
 * </Modal.Content>
 * ```
 */
interface ModalContentProps
  extends WithoutStyles<
    React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
  > {
  width?: keyof typeof widthClasses;
  height?: keyof typeof heightClasses;
  preventAccidentalClose?: boolean;
  skipOverlay?: boolean;
  background?: "default" | "gray";
  /** Content rendered below the modal card, floating with gap-4 (1rem) separation.
   *  Stays inside DialogPrimitive.Content for proper focus management. */
  bottomSlot?: React.ReactNode;
}
const ModalContent = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Content>,
  ModalContentProps
>(
  (
    {
      children,
      width = "md",
      height = "fit",
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

    // Reset state when modal closes or opens
    const resetState = React.useCallback(() => {
      setHasAttemptedClose(false);
      hasUserTypedRef.current = false;
    }, []);

    // Handle input events to detect typing
    const handleInput = React.useCallback((e: Event) => {
      // Early exit if already detected typing (performance optimization)
      if (hasUserTypedRef.current) {
        return;
      }

      // Only trust events triggered by actual user interaction
      if (!e.isTrusted) {
        return;
      }

      const target = e.target as HTMLElement;

      // Only handle input and textarea elements
      if (
        !(
          target instanceof HTMLInputElement ||
          target instanceof HTMLTextAreaElement
        )
      ) {
        return;
      }

      // Skip non-text inputs
      if (
        target.type === "hidden" ||
        target.type === "submit" ||
        target.type === "button" ||
        target.type === "checkbox" ||
        target.type === "radio"
      ) {
        return;
      }
      // Mark that user has typed something
      hasUserTypedRef.current = true;
    }, []);

    // Keep track of the container node for cleanup
    const containerNodeRef = React.useRef<HTMLDivElement | null>(null);

    // Callback ref to attach event listener when element mounts
    const contentRef = React.useCallback(
      (node: HTMLDivElement | null) => {
        // Cleanup previous listener if exists
        if (containerNodeRef.current) {
          containerNodeRef.current.removeEventListener(
            "input",
            handleInput,
            true
          );
        }

        // Attach new listener if node exists
        if (node) {
          node.addEventListener("input", handleInput, true);
          containerNodeRef.current = node;
        } else {
          containerNodeRef.current = null;
        }
      },
      [handleInput]
    );

    // Check if user has typed anything
    const hasModifiedInputs = React.useCallback(() => {
      return hasUserTypedRef.current;
    }, []);

    // Handle escape key and outside clicks
    const handleInteractOutside = React.useCallback(
      (e: Event) => {
        // If preventAccidentalClose is disabled, always allow immediate close
        if (!preventAccidentalClose) {
          setHasAttemptedClose(false);
          return;
        }

        // If preventAccidentalClose is enabled, check if user has modified inputs
        if (hasModifiedInputs()) {
          if (!hasAttemptedClose) {
            // First attempt: prevent close and focus the close button
            e.preventDefault();
            setHasAttemptedClose(true);
            setTimeout(() => {
              closeButtonRef.current?.focus();
            }, 0);
          } else {
            // Second attempt: allow close
            setHasAttemptedClose(false);
          }
        } else {
          // No modified inputs: allow immediate close
          setHasAttemptedClose(false);
        }
      },
      [preventAccidentalClose, hasModifiedInputs, hasAttemptedClose]
    );

    const handleRef = (node: HTMLDivElement | null) => {
      // Handle forwarded ref
      if (typeof ref === "function") {
        ref(node);
      } else if (ref) {
        ref.current = node;
      }
      // Handle content ref with event listener
      contentRef(node);
    };

    const { centerX, centerY, hasContainerCenter } = useContainerCenter();

    const animationClasses = cn(
      "data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0",
      "data-[state=open]:zoom-in-95 data-[state=closed]:zoom-out-95",
      "data-[state=open]:slide-in-from-top-1/2 data-[state=closed]:slide-out-to-top-1/2",
      "duration-200"
    );

    const containerStyle: React.CSSProperties | undefined = hasContainerCenter
      ? ({
          left: centerX,
          top: centerY,
          "--tw-enter-translate-x": "-50%",
          "--tw-exit-translate-x": "-50%",
          "--tw-enter-translate-y": "-50%",
          "--tw-exit-translate-y": "-50%",
        } as React.CSSProperties)
      : undefined;

    const positionClasses = cn(
      "fixed -translate-x-1/2 -translate-y-1/2",
      !hasContainerCenter && "left-1/2 top-1/2"
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
          hasAttemptedClose,
          setHasAttemptedClose,
          height,
          hasDescription,
          setHasDescription,
        }}
      >
        <DialogPrimitive.Portal>
          {!skipOverlay && <ModalOverlay />}
          {bottomSlot ? (
            // With bottomSlot: use asChild to wrap card + slot in a flex column
            <DialogPrimitive.Content
              asChild
              ref={handleRef}
              {...dialogEventHandlers}
            >
              <div
                style={containerStyle}
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
                <div className="w-full flex-shrink-0">{bottomSlot}</div>
              </div>
            </DialogPrimitive.Content>
          ) : (
            // Without bottomSlot: original single-element rendering
            <DialogPrimitive.Content
              ref={handleRef}
              style={containerStyle}
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

/**
 * Modal Header Component
 *
 * Container for header content with optional bottom shadow. All header visuals
 * (icon, title, description, close button) are now controlled via this single
 * component using props, so no additional subcomponents are required.
 *
 * @example
 * ```tsx
 * <Modal.Header icon={SvgWarning} title="Confirm Action" description="Are you sure?" />
 *
 * // With custom content
 * // Children render below the provided title/description stack.
 * <Modal.Header icon={SvgFile} title="Select Files">
 *   <InputTypeIn placeholder="Search..." />
 * </Modal.Header>
 * ```
 */
interface ModalHeaderProps extends WithoutStyles<SectionProps> {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description?: string;
  onClose?: () => void;
}
const ModalHeader = React.forwardRef<HTMLDivElement, ModalHeaderProps>(
  ({ icon: Icon, title, description, onClose, children, ...props }, ref) => {
    const { closeButtonRef, setHasDescription } = useModalContext();

    // useLayoutEffect ensures aria-describedby is set before paint,
    // so screen readers announce the description when the dialog opens
    React.useLayoutEffect(() => {
      setHasDescription(!!description);
    }, [description, setHasDescription]);

    return (
      <Section ref={ref} padding={1} alignItems="start" height="fit" {...props}>
        <Section gap={0.5}>
          <Section
            gap={0}
            padding={0}
            flexDirection="row"
            justifyContent="between"
          >
            {/*
              The `h-[1.5rem]` and `w-[1.5rem]` were added as backups here.
              However, prop-resolution technically resolves to choosing classNames over size props, so technically the `size={24}` is the backup.
              We specify both to be safe.

              # Note
              1.5rem === 24px
            */}
            <Icon className="stroke-text-04 h-[1.5rem] w-[1.5rem]" size={24} />
            {onClose && (
              <div
                tabIndex={-1}
                ref={closeButtonRef as React.RefObject<HTMLDivElement>}
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
            )}
          </Section>

          <Section alignItems="start" gap={0}>
            <DialogPrimitive.Title asChild>
              <Text headingH3>{title}</Text>
            </DialogPrimitive.Title>
            {description && (
              <DialogPrimitive.Description asChild>
                <Text secondaryBody text03>
                  {description}
                </Text>
              </DialogPrimitive.Description>
            )}
          </Section>
        </Section>
        {children}
      </Section>
    );
  }
);
ModalHeader.displayName = "ModalHeader";

/**
 * Modal Body Component
 *
 * Content area for the main modal content.
 *
 * @example
 * ```tsx
 * <Modal.Body>
 *   {/* Content *\/}
 * </Modal.Body>
 * ```
 */
interface ModalBodyProps extends WithoutStyles<SectionProps> {
  twoTone?: boolean;
}
const ModalBody = React.forwardRef<HTMLDivElement, ModalBodyProps>(
  ({ twoTone = true, children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          twoTone && "bg-background-tint-01",
          "h-full min-h-0 overflow-y-auto w-full"
        )}
      >
        <Section padding={1} gap={1} alignItems="start" {...props}>
          {children}
        </Section>
      </div>
    );
  }
);
ModalBody.displayName = "ModalBody";

/**
 * Modal Footer Component
 *
 * Footer section for actions/buttons.
 *
 * @example
 * ```tsx
 * // Right-aligned buttons
 * <Modal.Footer>
 *   <Button secondary>Cancel</Button>
 *   <Button primary>Confirm</Button>
 * </Modal.Footer>
 * ```
 */
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

export default Object.assign(ModalRoot, {
  Content: ModalContent,
  Header: ModalHeader,
  Body: ModalBody,
  Footer: ModalFooter,
});

// ============================================================================
// Common Layouts
// ============================================================================

export interface BasicModalFooterProps {
  left?: React.ReactNode;
  cancel?: React.ReactNode;
  submit?: React.ReactNode;
}

export function BasicModalFooter({
  left,
  cancel,
  submit,
}: BasicModalFooterProps) {
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
