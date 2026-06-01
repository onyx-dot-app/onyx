// Fallback for any tool packet without a dedicated renderer, so the timeline
// never shows a blank step.

import { useMemo } from "react";

import type { Packet } from "@/lib/types";
import type { MessageRendererProps } from "@/components/message/interfaces";
import {
  getToolName,
  getToolIconName,
  isToolComplete,
} from "@/state/timeline/toolDisplayHelpers";
import { useFireOnComplete } from "@/state/timeline/hooks/useFireOnComplete";

export function GenericToolRenderer({
  packets,
  onComplete,
  children,
}: MessageRendererProps<Packet>) {
  const complete = useMemo(() => isToolComplete(packets), [packets]);

  useFireOnComplete(complete, onComplete);

  return children([
    {
      icon: getToolIconName(packets),
      status: getToolName(packets),
      content: null,
      supportsCollapsible: false,
    },
  ]);
}

export default GenericToolRenderer;
