// Timeline Components - New UI architecture for AgentMessage
// These components provide a timeline-based view for displaying agent actions

// Core Components
export {
  AgentTimeline,
  StepContainer,
  type AgentTimelineProps,
  type StepContainerProps,
} from "./AgentTimeline";
export {
  TimelineRendererComponent,
  type TimelineRendererComponentProps,
  type TimelineRendererResult,
} from "./TimelineRendererComponent";

// Registries
export {
  getIconForPackets,
  getNameForPackets,
  getIconTypeForPackets,
  type IconType,
} from "./iconRegistry";

// Transformers
export {
  transformPacketGroup,
  transformPacketGroups,
  groupStepsByTurn,
  type TransformedStep,
  type TurnGroup,
} from "./transformers";
