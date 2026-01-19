export { AgentTimeline, type AgentTimelineProps } from "./AgentTimeline";
export { StepContainer, type StepContainerProps } from "./StepContainer";
export {
  TimelineRendererComponent,
  type TimelineRendererComponentProps,
  type TimelineRendererResult,
} from "./TimelineRendererComponent";

export {
  transformPacketGroup,
  transformPacketGroups,
  groupStepsByTurn,
  type TransformedStep,
  type TurnGroup,
} from "./transformers";

// Re-export hooks
export { useTimelineExpansion, useTimelineMetrics } from "./hooks";
export type {
  TimelineExpansionState,
  TimelineMetrics,
  UniqueTool,
} from "./hooks";

// Re-export utils
export {
  COMPACT_SUPPORTED_PACKET_TYPES,
  isResearchAgentPackets,
  stepSupportsCompact,
} from "./utils";
