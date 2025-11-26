"use client";

import React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { cn } from "@/lib/utils";
import { SvgProps } from "@/icons";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgX from "@/icons/x";

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
 * Modal Portal Component
 *
 * Wrapper around Radix Dialog.Portal for rendering modal in a portal.
 */
const ModalPortal = DialogPrimitive.Portal;

/**
 * Modal Close Component
 *
 * Wrapper around Radix Dialog.Close for close triggers.
 */
const ModalClose = DialogPrimitive.Close;

/**
 * Modal Overlay Component
 *
 * Backdrop overlay that appears behind the modal.
 *
 * @example
 * ```tsx
 * <Modal.Overlay className="bg-custom-overlay" />
 * ```
 */
const ModalOverlay = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      "fixed inset-0 z-[2000] bg-mask-03 backdrop-blur-03 pointer-events-none",
      "data-[state=open]:animate-in data-[state=closed]:animate-out",
      "data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0",
      className
    )}
    {...props}
  />
));
ModalOverlay.displayName = DialogPrimitive.Overlay.displayName;

/**
 * Modal Context for managing close button ref and warning state
 */
interface ModalContextValue {
  closeButtonRef: React.RefObject<HTMLDivElement | null>;
  hasAttemptedClose: boolean;
  setHasAttemptedClose: (value: boolean) => void;
}

const ModalContext = React.createContext<ModalContextValue | null>(null);

const useModalContext = () => {
  const context = React.useContext(ModalContext);
  if (!context) {
    throw new Error("Modal compound components must be used within Modal");
  }
  return context;
};

/**
 * Size class names mapping for modal variants
 */
const sizeClassNames = {
  large: ["w-[80dvw]", "h-[80dvh]"],
  medium: ["w-[60rem]", "h-fit"],
  small: ["w-[32rem]", "h-[30rem]"],
  tall: ["w-[32rem]", "max-h-[calc(100dvh-4rem)]"],
  mini: ["w-[32rem]", "h-fit"],
} as const;

/**
 * Modal Content Component
 *
 * Main modal container with default styling. Size and other styles controlled via className or size prop.
 *
 * @example
 * ```tsx
 * // Using size variants
 * <Modal.Content large>
 *   {/* Main modal: w-[80dvw] h-[80dvh] *\/}
 * </Modal.Content>
 *
 * <Modal.Content medium>
 *   {/* Medium modal: w-[60rem] h-fit *\/}
 * </Modal.Content>
 *
 * <Modal.Content small>
 *   {/* Small modal: w-[32rem] h-[30rem] *\/}
 * </Modal.Content>
 *
 * <Modal.Content tall>
 *   {/* Tall modal: w-[32rem] *\/}
 * </Modal.Content>
 *
 * <Modal.Content mini>
 *   {/* Mini modal: w-[32rem] h-fit *\/}
 * </Modal.Content>
 *
 * // Custom size with className
 * // (Highly discouraged! Always try to default to predefined sizings, please.)
 * <Modal.Content className="w-[48rem]">
 *   {/* Custom sized modal *\/}
 * </Modal.Content>
 * ```
 */
interface ModalContentProps
  extends React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> {
  large?: boolean;
  medium?: boolean;
  small?: boolean;
  tall?: boolean;
  mini?: boolean;
  preventAccidentalClose?: boolean;
}
const ModalContent = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Content>,
  ModalContentProps
>(
  (
    {
      className,
      children,
      large,
      medium,
      small,
      tall,
      mini,
      preventAccidentalClose = true,
      ...props
    },
    ref
  ) => {
    const variant = large
      ? "large"
      : medium
        ? "medium"
        : small
          ? "small"
          : tall
            ? "tall"
            : mini
              ? "mini"
              : "medium";
    const closeButtonRef = React.useRef<HTMLDivElement>(null);
    const [hasAttemptedClose, setHasAttemptedClose] = React.useState(false);
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

    return (
      <ModalContext.Provider
        value={{ closeButtonRef, hasAttemptedClose, setHasAttemptedClose }}
      >
        <ModalPortal>
          <ModalOverlay />
          <DialogPrimitive.Content
            ref={(node) => {
              // Handle forwarded ref
              if (typeof ref === "function") {
                ref(node);
              } else if (ref) {
                ref.current = node;
              }
              // Handle content ref with event listener
              contentRef(node);
            }}
            className={cn(
              "fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[2001]",
              "bg-background-tint-00 border rounded-16 shadow-2xl",
              "flex flex-col overflow-hidden",
              "data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0",
              "data-[state=open]:zoom-in-95 data-[state=closed]:zoom-out-95",
              "data-[state=open]:slide-in-from-top-1/2 data-[state=closed]:slide-out-to-top-1/2",
              "duration-200",
              // Size variants
              sizeClassNames[variant],
              className
            )}
            onOpenAutoFocus={(e) => {
              // Reset typing detection when modal opens
              resetState();
              props.onOpenAutoFocus?.(e);
            }}
            onCloseAutoFocus={(e) => {
              // Reset typing detection when modal closes
              resetState();
              props.onCloseAutoFocus?.(e);
            }}
            onEscapeKeyDown={handleInteractOutside}
            onPointerDownOutside={handleInteractOutside}
            {...props}
          >
            {children}
          </DialogPrimitive.Content>
        </ModalPortal>
      </ModalContext.Provider>
    );
  }
);
ModalContent.displayName = DialogPrimitive.Content.displayName;

/**
 * Modal Header Component
 *
 * Container for header content with optional bottom shadow.
 * Use with Modal.Icon, Modal.Title, Modal.Description, and custom children.
 *
 * @example
 * ```tsx
 * <Modal.Header className="p-4" withBottomShadow>
 *   <Modal.Icon icon={SvgWarning} />
 *   <Modal.Title>Confirm Action</Modal.Title>
 *   <Modal.Description>Are you sure?</Modal.Description>
 * </Modal.Header>
 *
 * // With custom content
 * <Modal.Header className="bg-background-tint-01 p-6" withBottomShadow>
 *   <Modal.Icon icon={SvgFile} />
 *   <Modal.Title>Select Files</Modal.Title>
 *   <InputTypeIn placeholder="Search..." />
 * </Modal.Header>
 * ```
 */
interface ModalHeaderProps extends React.HTMLAttributes<HTMLDivElement> {
  icon: React.FunctionComponent<SvgProps>;
  title: string;
  description?: string;
  onClose?: () => void;
  withBottomShadow?: boolean;
}
const ModalHeader = React.forwardRef<HTMLDivElement, ModalHeaderProps>(
  (
    {
      withBottomShadow = false,
      icon: Icon,
      title,
      description,
      onClose,
      className,
      children,
      ...props
    },
    ref
  ) => {
    const { closeButtonRef } = useModalContext();

    return (
      <div
        ref={ref}
        className={cn(
          "relative z-10 flex flex-col gap-4 p-4",
          withBottomShadow && "shadow-01",
          className
        )}
        {...props}
      >
        <div className="flex flex-col">
          <div className="flex flex-row items-center justify-between">
            <Icon className={"w-[1.5rem] h-[1.5rem] stroke-text-04"} />
            <div ref={closeButtonRef as React.RefObject<HTMLDivElement>}>
              <ModalClose asChild>
                <IconButton icon={SvgX} internal onClick={onClose} />
              </ModalClose>
            </div>
          </div>
          <Text headingH3>{title}</Text>
          {description && (
            <Text secondaryBody text03>
              {description}
            </Text>
          )}
        </div>
        {children}
      </div>
    );
  }
);
ModalHeader.displayName = "ModalHeader";

/**
 * Modal Body Component
 *
 * Content area for the main modal content. All styling via className.
 *
 * @example
 * ```tsx
 * <Modal.Body className="p-4">
 *   {/* Content *\/}
 * </Modal.Body>
 *
 * // With custom background and overflow
 * <Modal.Body className="bg-background-tint-02 flex-1 overflow-auto p-6">
 *   {/* Scrollable content *\/}
 * </Modal.Body>
 * ```
 */
interface ModalBodyProps extends React.HTMLAttributes<HTMLDivElement> {}
const ModalBody = React.forwardRef<HTMLDivElement, ModalBodyProps>(
  ({ className, children, ...props }, ref) => {
    return (
      <div ref={ref} className={cn(className)} {...props}>
        {children}
      </div>
    );
  }
);
ModalBody.displayName = "ModalBody";

/**
 * Modal Footer Component
 *
 * Footer section for actions/buttons. All styling via className.
 *
 * @example
 * ```tsx
 * // Right-aligned buttons
 * <Modal.Footer className="flex justify-end gap-2 p-4">
 *   <Button secondary>Cancel</Button>
 *   <Button primary>Confirm</Button>
 * </Modal.Footer>
 *
 * // Space-between layout
 * <Modal.Footer className="flex justify-between p-4">
 *   <Text>3 files selected</Text>
 *   <Button>Done</Button>
 * </Modal.Footer>
 * ```
 */
interface ModalFooterProps extends React.HTMLAttributes<HTMLDivElement> {}
const ModalFooter = React.forwardRef<HTMLDivElement, ModalFooterProps>(
  ({ className, children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          "flex flex-row items-center justify-end gap-1",
          className
        )}
        {...props}
      >
        {children}
      </div>
    );
  }
);
ModalFooter.displayName = "ModalFooter";

export default Object.assign(ModalRoot, {
  Content: ModalContent,
  Header: ModalHeader,
  Body: ModalBody,
  Footer: ModalFooter,
});
