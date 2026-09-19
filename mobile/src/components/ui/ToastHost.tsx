import { Pressable, View } from "react-native";
import Animated, {
  FadeInDown,
  FadeOutUp,
  LinearTransition,
} from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Portal } from "@rn-primitives/portal";

import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import {
  MAX_VISIBLE_TOASTS,
  toast,
  useToasts,
  type ToastLevel,
} from "@/hooks/useToast";
import type { IconFunctionComponent } from "@/icons/types";
import SvgAlertCircle from "@/icons/alert-circle";
import SvgCheckSmall from "@/icons/check-small";
import SvgInfoSmall from "@/icons/info-small";
import SvgX from "@/icons/x";

const LEVEL_ICON: Record<ToastLevel, IconFunctionComponent> = {
  success: SvgCheckSmall,
  error: SvgAlertCircle,
  warning: SvgAlertCircle,
  info: SvgInfoSmall,
  default: SvgInfoSmall,
};

const LEVEL_ICON_CLASS: Record<ToastLevel, string> = {
  success: "text-status-success-05",
  error: "text-status-error-05",
  warning: "text-status-warning-05",
  info: "text-text-03",
  default: "text-text-03",
};

// The single, app-wide toast stack. Mounted once at the root; renders via the shared PortalHost so
// it floats above every screen. Toasts stack at the top and auto-dismiss (or tap to dismiss).
export function ToastHost() {
  const toasts = useToasts();
  const insets = useSafeAreaInsets();

  // Stay mounted even when empty so the last toast's exit animation can play.
  return (
    <Portal name="toast">
      <View
        pointerEvents="box-none"
        className="absolute inset-x-0 top-0 z-50 gap-8 px-16"
        style={{ paddingTop: insets.top + 8 }}
      >
        {toasts.slice(-MAX_VISIBLE_TOASTS).map((entry) => (
          <Animated.View
            key={entry.id}
            entering={FadeInDown.duration(180)}
            exiting={FadeOutUp.duration(150)}
            layout={LinearTransition.duration(180)}
          >
            <Pressable
              onPress={
                entry.dismissible ? () => toast.dismiss(entry.id) : undefined
              }
              className="flex-row items-start gap-8 rounded-12 border border-border-01 bg-background-neutral-00 px-12 py-10"
            >
              <Icon
                as={LEVEL_ICON[entry.level]}
                size={18}
                className={LEVEL_ICON_CLASS[entry.level]}
              />
              <View className="min-w-0 flex-1 gap-2">
                <Text font="secondary-body" color="text-04">
                  {entry.message}
                </Text>
                {entry.description ? (
                  <Text font="secondary-body" color="text-03">
                    {entry.description}
                  </Text>
                ) : null}
              </View>
              {entry.dismissible ? (
                <Icon as={SvgX} size={16} className="text-text-03" />
              ) : null}
            </Pressable>
          </Animated.View>
        ))}
      </View>
    </Portal>
  );
}
