"use client";

import * as React from "react";
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
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      "fixed inset-0 z-[2000] bg-mask-03 backdrop-blur-03",
      "data-[state=open]:animate-in data-[state=closed]:animate-out",
      "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
      className
    )}
    {...props}
  />
));
ModalOverlay.displayName = DialogPrimitive.Overlay.displayName;

/**
 * Modal Content Component
 *
 * Main modal container with default styling. Size and other styles controlled via className or size prop.
 *
 * @example
 * ```tsx
 * // Using size variants
 * <Modal.Content size="xs">
 *   {/* Extra small modal (27rem) *\/}
 * </Modal.Content>
 *
 * <Modal.Content size="sm">
 *   {/* Small modal (32rem) *\/}
 * </Modal.Content>
 *
 * <Modal.Content size="md">
 *   {/* Medium modal (60rem) *\/}
 * </Modal.Content>
 *
 * // Custom size with className
 * <Modal.Content className="w-[48rem]">
 *   {/* Custom sized modal *\/}
 * </Modal.Content>
 *
 * // Large modal with height
 * <Modal.Content className="w-[60rem] h-[80vh]">
 *   {/* Custom large modal *\/}
 * </Modal.Content>
 * ```
 */
const ModalContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
    hideCloseButton?: boolean;
    size?: "xs" | "sm" | "md";
  }
>(({ className, children, hideCloseButton, size, ...props }, ref) => (
  <ModalPortal>
    <ModalOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed left-[50%] top-[50%] z-[2001] translate-x-[-50%] translate-y-[-50%]",
        "bg-background-tint-00 border rounded-16 shadow-2xl",
        "flex flex-col overflow-hidden",
        "data-[state=open]:animate-in data-[state=closed]:animate-out",
        "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
        "data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
        "data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%]",
        "data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%]",
        "duration-200",
        // Size variants
        size === "xs" && "w-[27rem] max-h-[calc(100dvh-4rem)]",
        size === "sm" && "w-[32rem] max-h-[calc(100dvh-4rem)]",
        size === "md" && "w-[60rem] max-h-[calc(100dvh-4rem)]",
        className
      )}
      {...props}
    >
      {children}
    </DialogPrimitive.Content>
  </ModalPortal>
));
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
  withBottomShadow?: boolean;
}

const ModalHeader = React.forwardRef<HTMLDivElement, ModalHeaderProps>(
  ({ withBottomShadow = false, className, children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn("relative z-10", className)}
        style={
          withBottomShadow
            ? {
                boxShadow:
                  "0 2px 12px 0 var(--Shadow-02, rgba(0, 0, 0, 0.10)), 0 0 4px 1px var(--Shadow-01, rgba(0, 0, 0, 0.05))",
              }
            : undefined
        }
        {...props}
      >
        {children}
      </div>
    );
  }
);
ModalHeader.displayName = "ModalHeader";

/**
 * Modal Icon Component
 *
 * Icon component for modal header.
 *
 * @example
 * ```tsx
 * <Modal.Icon icon={SvgWarning} />
 * <Modal.Icon icon={SvgFile} className="w-8 h-8 stroke-blue-500" />
 * ```
 */
interface ModalIconProps extends React.HTMLAttributes<HTMLDivElement> {
  icon: React.FunctionComponent<SvgProps>;
}

const ModalIcon = React.forwardRef<HTMLDivElement, ModalIconProps>(
  ({ icon: Icon, className, ...props }, ref) => {
    return (
      <div ref={ref} {...props}>
        <Icon
          className={cn("w-[1.5rem] h-[1.5rem] stroke-text-04", className)}
        />
      </div>
    );
  }
);
ModalIcon.displayName = "ModalIcon";

/**
 * Modal Close Button Component
 *
 * Absolutely positioned close button. Place inside Modal.Content.
 *
 * @example
 * ```tsx
 * <Modal.Content>
 *   <Modal.CloseButton />
 *   <Modal.Header>...</Modal.Header>
 * </Modal.Content>
 *
 * // Custom positioning
 * <Modal.CloseButton className="top-2 right-2" />
 * ```
 */
interface ModalCloseButtonProps extends React.HTMLAttributes<HTMLDivElement> {
  onClose?: () => void;
}

const ModalCloseButton = React.forwardRef<
  HTMLDivElement,
  ModalCloseButtonProps
>(({ onClose, className, ...props }, ref) => {
  return (
    <div
      ref={ref}
      className={cn("absolute top-4 right-4 z-20", className)}
      {...props}
    >
      <ModalClose asChild>
        <IconButton icon={SvgX} internal onClick={onClose} />
      </ModalClose>
    </div>
  );
});
ModalCloseButton.displayName = "ModalCloseButton";

/**
 * Modal Title Component
 *
 * Title wrapper with default styling. Fully customizable via className.
 * Uses Radix Dialog.Title for accessibility.
 *
 * @example
 * ```tsx
 * <Modal.Title>Confirm Action</Modal.Title>
 * <Modal.Title className="text-4xl font-bold">Custom Styled Title</Modal.Title>
 * ```
 */
const ModalTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, children, ...props }, ref) => (
  <DialogPrimitive.Title ref={ref} asChild {...props}>
    <Text headingH3 className={cn("w-full text-left", className)}>
      {children}
    </Text>
  </DialogPrimitive.Title>
));
ModalTitle.displayName = DialogPrimitive.Title.displayName;

/**
 * Modal Description Component
 *
 * Description wrapper with default styling. Fully customizable via className.
 * Uses Radix Dialog.Description for accessibility.
 *
 * @example
 * ```tsx
 * <Modal.Description>Are you sure you want to continue?</Modal.Description>
 * <Modal.Description className="text-lg">Custom styled description</Modal.Description>
 * ```
 */
const ModalDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, children, ...props }, ref) => (
  <DialogPrimitive.Description ref={ref} asChild {...props}>
    <Text secondaryBody text02 className={className}>
      {children}
    </Text>
  </DialogPrimitive.Description>
));
ModalDescription.displayName = DialogPrimitive.Description.displayName;

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
      <div ref={ref} className={cn(className)} {...props}>
        {children}
      </div>
    );
  }
);
ModalFooter.displayName = "ModalFooter";

export const Modal = Object.assign(ModalRoot, {
  Portal: ModalPortal,
  Close: ModalClose,
  Overlay: ModalOverlay,
  Content: ModalContent,
  Header: ModalHeader,
  Icon: ModalIcon,
  CloseButton: ModalCloseButton,
  Title: ModalTitle,
  Description: ModalDescription,
  Body: ModalBody,
  Footer: ModalFooter,
});
