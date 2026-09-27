/*
 * Children are deliberately not wrapped in a ScrollView: callers cap and scroll their own region
 * (the file picker only its recents list, the reasoning sheet keeps a footer outside the scroller),
 * so one here would nest scrollers.
 */
import type { ReactNode } from "react";
import { Modal, Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Text } from "@/components/ui/text";
import SvgChevronLeft from "@/icons/chevron-left";
import SvgX from "@/icons/x";

type SheetBackground = "default" | "gray";

// Literal class strings so NativeWind's compiler sees them.
const SHEET_BACKGROUNDS: Record<SheetBackground, string> = {
  default: "bg-background-tint-00",
  gray: "bg-background-tint-01",
};

interface SheetProps {
  visible: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  background?: SheetBackground;
  onBack?: () => void;
  // Fires after the dismiss animation finishes; iOS drops a picker presented before then.
  onDismiss?: () => void;
  children: ReactNode;
}

function Sheet({
  visible,
  onClose,
  title,
  subtitle,
  background = "default",
  onBack,
  onDismiss,
  children,
}: SheetProps) {
  const insets = useSafeAreaInsets();

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
      onDismiss={onDismiss}
      statusBarTranslucent
    >
      {/* `accessible={false}` on both wrappers: Pressable defaults it to true, and an accessibility
          element hides its descendants from VoiceOver — the sheet would be read as one blob and the
          Close/row buttons would be unreachable. Touch is unaffected. */}
      <Pressable
        accessible={false}
        className="flex-1 justify-end bg-mask-03"
        onPress={onClose}
      >
        {/* Stop taps inside the sheet from dismissing it. */}
        <Pressable
          accessible={false}
          onPress={() => {}}
          className={cn(
            // Separates the card in dark mode, where it and the page behind are both near-black.
            "rounded-t-20 border-t border-border-01 px-16 pt-16",
            SHEET_BACKGROUNDS[background],
          )}
          style={{ paddingBottom: insets.bottom + 16 }}
        >
          <View
            className={cn(
              "mb-8 flex-row justify-between gap-4",
              subtitle ? "items-start" : "items-center",
            )}
          >
            {onBack ? (
              <Button
                icon={SvgChevronLeft}
                prominence="tertiary"
                size="sm"
                accessibilityLabel="Back"
                onPress={onBack}
              />
            ) : null}
            <View className="flex-1">
              <Text font="main-content-emphasis" color="text-04">
                {title}
              </Text>
              {subtitle ? (
                <Text font="secondary-body" color="text-03">
                  {subtitle}
                </Text>
              ) : null}
            </View>
            <Button
              icon={SvgX}
              prominence="tertiary"
              size="sm"
              accessibilityLabel="Close"
              onPress={onClose}
            />
          </View>

          {children}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

export { Sheet, type SheetProps, type SheetBackground };
