// Timeline Components - New UI architecture for AgentMessage
// These components provide a timeline-based view for displaying agent actions

// Core Components
export { AgentStep, type AgentStepProps, type IconType } from "./AgentStep";
export {
  AgentTimeline,
  StepContainer,
  type AgentTimelineProps,
  type StepContainerProps,
} from "./AgentTimeline";

// Registries
export {
  getIconForPackets,
  getNameForPackets,
  getIconTypeForPackets,
  isToolPacketGroup,
  isDisplayPacketGroup,
} from "./iconRegistry";

// Transformers
export {
  transformPacketGroup,
  transformPacketGroups,
  groupStepsByTurn,
  type TransformedStep,
  type TurnGroup,
} from "./transformers";
