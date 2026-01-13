// Timeline Components - New UI architecture for AgentMessage
// These components provide a timeline-based view for displaying agent actions

// Core Components
export { AgentStep, type AgentStepProps, type IconType } from "./AgentStep";
export {
  AgentTimeline,
  StepIcon,
  StepConnector,
  StepContainer,
  getFirstStep,
  shouldShowConnector,
  type AgentTimelineProps,
  type StepIconProps,
  type StepConnectorProps,
  type StepContainerProps,
} from "./AgentTimeline";
export {
  StepContent,
  StepContentSimple,
  type StepContentProps,
} from "./StepContent";
export { ParallelSteps, type ParallelStepsProps } from "./ParallelSteps";

// Registries
export {
  getIconForPackets,
  getNameForPackets,
  getIconTypeForPackets,
  isToolPacketGroup,
  isDisplayPacketGroup,
  ICON_SIZE_CLASS,
} from "./iconRegistry";

export {
  findRendererForPackets,
  registerRenderer,
  getRegisteredRenderers,
} from "./rendererRegistry";

// Transformers
export {
  transformPacketGroup,
  transformPacketGroups,
  groupStepsByTurn,
  splitStepsByType,
  getToolTurnGroups,
  getDisplaySteps,
  type TransformedStep,
  type TurnGroup,
} from "./transformers";
