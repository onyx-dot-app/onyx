/*
 * Bottom-sheet shell: scrim, card, safe-area padding and the title/close header. The only Modal in
 * the app — every sheet composes this.
 *
 * The body is whatever the caller passes, and the caller caps its own height: the sheets sharing
 * this shell scroll different regions (the file picker scrolls only its recents list, and the
 * reasoning sheet keeps a footer outside the scroller), so an outer ScrollView would nest scrollers.
 *
 * Also the actions menu's container seam. Web anchors that menu to its trigger, but the mobile
 * composer is keyboard-sticky, so an anchored panel would chase a moving anchor. Swapping to one
 * later means changing this component, not its callers.
 */
import type { ReactNode } from "react";
import { Modal, Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Text } from "@/components/ui/text";
import SvgX from "@/icons/x";

// Mirrors Opal's `.opal-modal-card[data-background]`. Literal class strings so NativeWind's
// compiler sees them. Both tokens flip with the active theme, so `gray` reads as recessed in light
// mode (#fafafa on #ffffff) and raised in dark (#19191e on #000000).
type SheetBackground = "default" | "gray";

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
      {/* Same scrim token as web's modal overlay; its backdrop-blur-03 has no RN analog.
          `accessible={false}` on both wrappers: Pressable defaults it to true, and a view that is
          an accessibility element hides its descendants from VoiceOver — the whole sheet would be
          read as one blob and Close/row buttons would be unreachable. Touch is unaffected. */}
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
            // The border, not a shadow, is what separates the card: in dark mode both it and the
            // page behind the scrim are near-black.
            "rounded-t-20 border-t border-border-01 px-16 pt-16",
            SHEET_BACKGROUNDS[background],
          )}
          style={{ paddingBottom: insets.bottom + 16 }}
        >
          {/* A subtitle makes the left column taller than the close button, so top-align only
              then; a lone title reads better centred against it. */}
          <View
            className={cn(
              "mb-8 flex-row justify-between",
              subtitle ? "items-start" : "items-center",
            )}
          >
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
