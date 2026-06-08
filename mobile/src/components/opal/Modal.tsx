import type { ReactNode } from "react";
import { Pressable, View } from "react-native";
import * as DialogPrimitive from "@rn-primitives/dialog";

import { cn } from "@/lib/cn";
import { Text } from "@/components/opal/Text";
import { useToken } from "@/theme/ThemeProvider";

// Requires a <PortalHost /> (from @rn-primitives/portal) near the app root.

interface ModalProps {
  visible: boolean;
  onClose: () => void;
  title?: string;
  children?: ReactNode;
  className?: string;
  hideClose?: boolean;
}

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

const ModalPrimitive = DialogPrimitive;

export { Modal, ModalPrimitive, type ModalProps };
