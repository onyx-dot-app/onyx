import { JSX } from "react";
import {
  FiCircle,
  FiCode,
  FiGlobe,
  FiImage,
  FiLink,
  FiList,
  FiSearch,
  FiTool,
  FiUsers,
  FiMessageSquare,
} from "react-icons/fi";
import { BrainIcon } from "@/components/icons/icons";
import {
  Packet,
  PacketType,
  SearchToolPacket,
} from "@/app/chat/services/streamingModels";
import { constructCurrentSearchState } from "../renderers/SearchToolRenderer";
import { IconType } from "./AgentStep";

/**
 * Icon size class for timeline icons
 */
export const ICON_SIZE_CLASS = "w-4 h-4";

/**
 * Registry of packet types to their icons
 * Extensible - add new entries for new tool types
 */
type IconFactory = (packets: Packet[]) => JSX.Element;

const PACKET_TYPE_ICON_REGISTRY: Partial<Record<PacketType, IconFactory>> = {
  [PacketType.SEARCH_TOOL_START]: (packets) => {
    const searchState = constructCurrentSearchState(
      packets as SearchToolPacket[]
    );
    return searchState.isInternetSearch ? (
      <FiGlobe className={ICON_SIZE_CLASS} />
    ) : (
      <FiSearch className={ICON_SIZE_CLASS} />
    );
  },
  [PacketType.PYTHON_TOOL_START]: () => <FiCode className={ICON_SIZE_CLASS} />,
  [PacketType.FETCH_TOOL_START]: () => <FiLink className={ICON_SIZE_CLASS} />,
  [PacketType.CUSTOM_TOOL_START]: () => <FiTool className={ICON_SIZE_CLASS} />,
  [PacketType.IMAGE_GENERATION_TOOL_START]: () => (
    <FiImage className={ICON_SIZE_CLASS} />
  ),
  [PacketType.DEEP_RESEARCH_PLAN_START]: () => (
    <FiList className={ICON_SIZE_CLASS} />
  ),
  [PacketType.RESEARCH_AGENT_START]: () => (
    <FiUsers className={ICON_SIZE_CLASS} />
  ),
  [PacketType.REASONING_START]: () => <BrainIcon className={ICON_SIZE_CLASS} />,
  [PacketType.MESSAGE_START]: () => (
    <FiMessageSquare className={ICON_SIZE_CLASS} />
  ),
};

/**
 * Default icon for unknown packet types
 */
const DEFAULT_ICON = () => <FiCircle className={ICON_SIZE_CLASS} />;

/**
 * Get the icon for a packet group based on the first packet's type
 */
export function getIconForPackets(packets: Packet[]): JSX.Element {
  const firstPacket = packets[0];
  if (!firstPacket) return DEFAULT_ICON();

  const packetType = firstPacket.obj.type as PacketType;
  const iconFactory = PACKET_TYPE_ICON_REGISTRY[packetType];

  if (iconFactory) {
    return iconFactory(packets);
  }

  return DEFAULT_ICON();
}

/**
 * Registry of packet types to their display names
 */
const PACKET_TYPE_NAME_REGISTRY: Partial<
  Record<PacketType, (packets: Packet[]) => string>
> = {
  [PacketType.SEARCH_TOOL_START]: (packets) => {
    const searchState = constructCurrentSearchState(
      packets as SearchToolPacket[]
    );
    return searchState.isInternetSearch ? "Web Search" : "Internal Search";
  },
  [PacketType.PYTHON_TOOL_START]: () => "Code Interpreter",
  [PacketType.FETCH_TOOL_START]: () => "Open URLs",
  [PacketType.CUSTOM_TOOL_START]: (packets) =>
    (packets[0]?.obj as { tool_name?: string }).tool_name || "Custom Tool",
  [PacketType.IMAGE_GENERATION_TOOL_START]: () => "Generate Image",
  [PacketType.DEEP_RESEARCH_PLAN_START]: () => "Generating plan",
  [PacketType.RESEARCH_AGENT_START]: () => "Research Agent",
  [PacketType.REASONING_START]: () => "Thinking",
  [PacketType.MESSAGE_START]: () => "Response",
};

/**
 * Get the display name for a packet group
 */
export function getNameForPackets(packets: Packet[]): string {
  const firstPacket = packets[0];
  if (!firstPacket) return "Step";

  const packetType = firstPacket.obj.type as PacketType;
  const nameFactory = PACKET_TYPE_NAME_REGISTRY[packetType];

  if (nameFactory) {
    return nameFactory(packets);
  }

  return "Step";
}

/**
 * Determine the icon type (loading state) based on packet group
 */
export function getIconTypeForPackets(packets: Packet[]): IconType {
  // Check for error
  const hasError = packets.some((p) => p.obj.type === PacketType.ERROR);
  if (hasError) return "error";

  // Check for completion
  const firstPacket = packets[0];
  if (!firstPacket) return "default";

  // For research agents, only parent-level SECTION_END indicates completion
  if (firstPacket.obj.type === PacketType.RESEARCH_AGENT_START) {
    const isComplete = packets.some(
      (p) =>
        (p.obj.type === PacketType.SECTION_END ||
          p.obj.type === PacketType.ERROR) &&
        (p.placement.sub_turn_index === undefined ||
          p.placement.sub_turn_index === null)
    );
    return isComplete ? "complete" : "loading";
  }

  // For other tools, any SECTION_END indicates completion
  const isComplete = packets.some(
    (p) =>
      p.obj.type === PacketType.SECTION_END || p.obj.type === PacketType.ERROR
  );

  return isComplete ? "complete" : "loading";
}

/**
 * Helper to check if packets represent a tool (vs message/display content)
 */
export function isToolPacketGroup(packets: Packet[]): boolean {
  const firstPacket = packets[0];
  if (!firstPacket) return false;

  const toolTypes: PacketType[] = [
    PacketType.SEARCH_TOOL_START,
    PacketType.PYTHON_TOOL_START,
    PacketType.FETCH_TOOL_START,
    PacketType.CUSTOM_TOOL_START,
    PacketType.REASONING_START,
    PacketType.DEEP_RESEARCH_PLAN_START,
    PacketType.RESEARCH_AGENT_START,
  ];

  return toolTypes.includes(firstPacket.obj.type as PacketType);
}

/**
 * Helper to check if packets represent displayable content (message, image)
 */
export function isDisplayPacketGroup(packets: Packet[]): boolean {
  const firstPacket = packets[0];
  if (!firstPacket) return false;

  const displayTypes: PacketType[] = [
    PacketType.MESSAGE_START,
    PacketType.IMAGE_GENERATION_TOOL_START,
    PacketType.PYTHON_TOOL_START,
  ];

  return displayTypes.includes(firstPacket.obj.type as PacketType);
}
