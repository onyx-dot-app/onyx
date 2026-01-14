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
export { StepContent, type StepContentProps } from "./StepContent";
export { ParallelSteps, type ParallelStepsProps } from "./ParallelSteps";

// New composable components (use instead of AgentTimeline for full layout control)
/**
 * @deprecated Use usePacketProcessor instead, which now returns toolTurnGroups directly.
 * This hook is kept for backwards compatibility but its logic has been integrated
 * into usePacketProcessor for better performance (single-pass categorization).
 */
export {
  useAgentTimeline,
  type UseAgentTimelineResult,
} from "./useAgentTimeline";
export { TimelineIcons, type TimelineIconsProps } from "./TimelineIcons";
export { TimelineContent, type TimelineContentProps } from "./TimelineContent";

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
