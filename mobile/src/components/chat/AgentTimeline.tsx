// Simple port of web's AgentTimeline (web/src/app/app/message/messageComponents/timeline). The
// assistant message is a vertical stack: this timeline — the agent avatar in a 36px rail plus a
// status header — sits above the answer text. Web-faithful minus the rich step content: the
// reasoning/tool STEP rows are scaffolded (rail dot + 1px connector + label) but fed no data yet,
// since the mobile stream doesn't parse reasoning/tool packets. The loading state mirrors web's
// shimmering "Thinking…" label (web uses a CSS gradient sweep; RN approximates it with an opacity
// pulse on the reanimated UI thread).
import { useEffect } from "react";
import { View } from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";

import { AgentAvatar } from "@/components/avatars/AgentAvatar";
import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import { MinimalAgent } from "@/chat/agents";
import { cn } from "@/lib/utils";
import type { IconFunctionComponent } from "@/icons/types";

// web timeline rail width (--timeline-rail-width = 2.25rem = 36px) and header avatar size (24).
const RAIL = "w-36";
const AVATAR_SIZE = 24;

export type TimelineStepStatus = "running" | "done" | "error";

export interface TimelineStepData {
  key: string;
  label: string;
  status: TimelineStepStatus;
  // Tool/step icon when available; falls back to a status-colored dot.
  icon?: IconFunctionComponent;
}

interface AgentTimelineProps {
  agent: MinimalAgent | null;
  // web's EMPTY state: the run has begun but no answer content has arrived → shimmer "Thinking…".
  isLoading: boolean;
  // Reasoning/tool steps; empty until the mobile stream parses those packets (kept as a seam).
  steps?: TimelineStepData[];
}

export function AgentTimeline({
  agent,
  isLoading,
  steps = [],
}: AgentTimelineProps) {
  return (
    <View>
      {/* Header row (web TimelineHeaderRow): avatar centered in the rail + status label beside it. */}
      <View className="h-36 flex-row items-center">
        <View className={cn("h-36 items-center justify-center", RAIL)}>
          {agent ? <AgentAvatar agent={agent} size={AVATAR_SIZE} /> : null}
        </View>
        {isLoading ? <ThinkingLabel /> : null}
      </View>

      {steps.map((step, index) => (
        <TimelineStep
          key={step.key}
          step={step}
          isFirst={index === 0}
          isLast={index === steps.length - 1}
        />
      ))}
    </View>
  );
}

// web `.shimmer-text` gradient sweep → an opacity breathe (no masked-gradient dep for the simple port).
function ThinkingLabel() {
  const opacity = useSharedValue(0.5);
  useEffect(() => {
    opacity.value = withRepeat(
      withTiming(1, { duration: 900, easing: Easing.inOut(Easing.ease) }),
      -1,
      true,
    );
  }, [opacity]);
  const animatedStyle = useAnimatedStyle(() => ({ opacity: opacity.value }));
  return (
    <Animated.View style={animatedStyle}>
      <Text font="main-ui-action" color="text-03">
        Thinking…
      </Text>
    </Animated.View>
  );
}

// One reasoning/tool step: web TimelineRow (rail = 1px connector + a 12px icon/dot) + a muted label.
function TimelineStep({
  step,
  isFirst,
  isLast,
}: {
  step: TimelineStepData;
  isFirst: boolean;
  isLast: boolean;
}) {
  const isError = step.status === "error";
  return (
    <View className="flex-row">
      <View className={cn("items-center", RAIL)}>
        {/* connector above (web `bg-border-01`, `w-px`); hidden on the first step */}
        <View
          className={cn("h-8 w-[1px] bg-border-01", isFirst && "opacity-0")}
        />
        {step.icon ? (
          <Icon
            as={step.icon}
            size={12}
            className={isError ? "text-status-error-05" : "text-text-02"}
          />
        ) : (
          <View
            className={cn(
              "h-8 w-8 rounded-full",
              isError ? "bg-status-error-05" : "bg-text-04",
            )}
          />
        )}
        {/* connector below (flex-1); hidden on the last step */}
        <View
          className={cn("w-[1px] flex-1 bg-border-01", isLast && "opacity-0")}
        />
      </View>
      <View className="flex-1 py-4">
        <Text
          font="main-ui-muted"
          color={isError ? "status-error-05" : "text-04"}
        >
          {step.label}
        </Text>
      </View>
    </View>
  );
}
