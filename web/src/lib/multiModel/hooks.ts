"use client";

import { useMemo } from "react";
import { useCurrentMessageTree } from "@/app/app/stores/useChatSessionStore";
import { messageModelName } from "@/app/app/message/multiModel";

// Distinct models that produced a response anywhere in the current session,
// counting multi-model turns and model switches between turns. Surfaces that
// attribute responses to a model (e.g. the Retry label) stay expanded above 1.
export function useDistinctModelsUsed(): number {
  const messageTree = useCurrentMessageTree();
  return useMemo(() => {
    if (!messageTree) return 0;
    const names = new Set<string>();
    messageTree.forEach((m) => {
      const name = messageModelName(m);
      if (name) names.add(name);
    });
    return names.size;
  }, [messageTree]);
}
