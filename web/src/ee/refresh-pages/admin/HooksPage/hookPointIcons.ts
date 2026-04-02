import { SvgBubbleText, SvgFileBroadcast, SvgHookNodes } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";

const HOOK_POINT_ICONS: Record<string, IconFunctionComponent> = {
  document_ingestion: SvgFileBroadcast,
  query_processing: SvgBubbleText,
};

function getHookPointIcon(hookPoint: string): IconFunctionComponent {
  return HOOK_POINT_ICONS[hookPoint] ?? SvgHookNodes;
}

export { HOOK_POINT_ICONS, getHookPointIcon };
