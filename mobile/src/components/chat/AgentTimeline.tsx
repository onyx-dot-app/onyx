// Port of web's AgentTimeline (web/src/app/app/message/messageComponents/timeline): the agent
// avatar in a 36px rail plus a status header, sitting above the answer text.
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

// Mirrors web's --timeline-rail-width (36px); on mobile w-36 = 36px.
const RAIL = "w-36";
const AVATAR_SIZE = 24;

export type TimelineStepStatus = "running" | "done" | "error";

export interface TimelineStepData {
  key: string;
  label: string;
  status: TimelineStepStatus;
  icon?: IconFunctionComponent;
}

interface AgentTimelineProps {
  agent: MinimalAgent | null;
  // EMPTY state (web): run started but no answer content yet → shimmer "Thinking…".
  isLoading: boolean;
  // Empty until the mobile stream parses reasoning/tool packets (seam).
  steps?: TimelineStepData[];
}

export function AgentTimeline({
  agent,
  isLoading,
  steps = [],
}: AgentTimelineProps) {
  return (
    <View>
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

// Approximates web's .shimmer-text gradient sweep with an opacity pulse (no masked-gradient dep).
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
