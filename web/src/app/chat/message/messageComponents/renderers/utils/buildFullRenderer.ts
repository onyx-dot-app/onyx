import { IconType } from "react-icons";
import { FullChatState, MessageRenderer } from "../../interfaces";
import { Packet } from "@/app/chat/services/streamingModels";

export function buildFullRenderer<
  T extends Packet,
  S extends Partial<FullChatState>,
>(
  icon: IconType | null,
  extendedRenderer: MessageRenderer<T, S>,
  shortRenderer: MessageRenderer<T, S>
) {
  return {
    icon,
    extendedRenderer,
    shortRenderer,
  };
}
