"use client";

import { useCallback, useRef } from "react";
import { useBuildContext } from "@/app/craft/contexts/BuildContext";
import {
  VIDEO_BACKGROUND_CLICK_COUNT,
  VIDEO_BACKGROUND_CLICK_RESET_MS,
} from "@/app/craft/components/video-background/constants";

export function useVideoBackgroundToggleClick() {
  const { toggleVideoBackground } = useBuildContext();
  const clickCountRef = useRef(0);
  const lastClickRef = useRef(0);

  return useCallback(() => {
    const now = Date.now();
    if (now - lastClickRef.current > VIDEO_BACKGROUND_CLICK_RESET_MS) {
      clickCountRef.current = 0;
    }
    lastClickRef.current = now;
    clickCountRef.current += 1;
    if (clickCountRef.current >= VIDEO_BACKGROUND_CLICK_COUNT) {
      clickCountRef.current = 0;
      toggleVideoBackground();
    }
  }, [toggleVideoBackground]);
}
