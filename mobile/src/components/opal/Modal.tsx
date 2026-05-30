import type { ReactNode } from "react";
import { Pressable, View } from "react-native";
import * as DialogPrimitive from "@rn-primitives/dialog";

import { cn } from "@/lib/cn";
import { Text } from "@/components/opal/Text";
import { useToken } from "@/theme/ThemeProvider";

// ---------------------------------------------------------------------------
// Modal — a themed dialog built on @rn-primitives/dialog.
//
// API: a simple CONTROLLED component.
//
//   <Modal visible={open} onClose={() => setOpen(false)} title="Heading">
//     ...body...
//   </Modal>
//
// This is the cleaner API for app code (no need to thread Root/Trigger/Content
// manually). The trigger is owned by the caller — open the Modal by flipping
// `visible`. For callers who want the unstyled compound primitives (Trigger,
// Portal positioning, etc.), the raw rn-primitives parts are re-exported as
// `ModalPrimitive`.
//
// Requires a <PortalHost /> (from @rn-primitives/portal) near the app root.
// ---------------------------------------------------------------------------

interface ModalProps {
  /** Whether the modal is shown. Controlled by the caller. */
  visible: boolean;
  /** Called when the user dismisses (overlay press / close button / back). */
  onClose: () => void;
  /** Optional title rendered with the Opal `Text` heading preset. */
  title?: string;
  /** Modal body. */
  children?: ReactNode;
  /** Extra classes merged onto the content card. */
  className?: string;
  /** Hide the default top-right close affordance. Default: false. */
  hideClose?: boolean;
}

/**
 * Themed controlled dialog. The overlay is a semi-transparent scrim (the
 * `mask-03` token), the content is a `background-neutral-00` rounded, bordered,
 * padded card. The title uses the Opal `Text` component.
 */
function Modal({
  visible,
  onClose,
  title,
  children,
  className,
  hideClose = false,
}: ModalProps) {
  const scrim = useToken("mask-03");
  const closeColor = useToken("text-03");

  return (
    <DialogPrimitive.Root
      open={visible}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          style={{ backgroundColor: scrim }}
          className="absolute inset-0 items-center justify-center p-6"
        >
          <DialogPrimitive.Content
            className={cn(
              "w-full max-w-[420px] rounded-[16px] border border-border-02 bg-background-neutral-00 p-5",
              className,
            )}
          >
            {(title || !hideClose) && (
              <View className="mb-3 flex-row items-start justify-between gap-3">
                {title ? (
                  <DialogPrimitive.Title asChild>
                    <Text font="heading-h3" color="text-05" className="flex-1">
                      {title}
                    </Text>
                  </DialogPrimitive.Title>
                ) : (
                  <View className="flex-1" />
                )}
                {!hideClose && (
                  <DialogPrimitive.Close asChild>
                    <Pressable
                      hitSlop={8}
                      accessibilityRole="button"
                      accessibilityLabel="Close"
                      className="h-6 w-6 items-center justify-center"
                    >
                      <Text
                        font="main-content-body"
                        style={{ color: closeColor, fontSize: 18, lineHeight: 18 }}
                      >
                        {"✕"}
                      </Text>
                    </Pressable>
                  </DialogPrimitive.Close>
                )}
              </View>
            )}
            {children}
          </DialogPrimitive.Content>
        </DialogPrimitive.Overlay>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/**
 * The raw, unstyled rn-primitives dialog parts (Root / Trigger / Portal /
 * Overlay / Content / Title / Close). Use these directly when the simple
 * `<Modal>` controlled API is not flexible enough.
 */
const ModalPrimitive = DialogPrimitive;

export { Modal, ModalPrimitive, type ModalProps };
