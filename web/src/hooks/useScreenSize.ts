"use client";

import {
  DESKTOP_SMALL_BREAKPOINT_PX,
  MOBILE_SIDEBAR_BREAKPOINT_PX,
} from "@/lib/constants";
import { useState, useCallback } from "react";
import useOnMount from "@/hooks/useOnMount";

export interface ScreenSize {
  height: number;
  width: number;
  isMobile: boolean;
  isSmallScreen: boolean;
}

export default function useScreenSize(): ScreenSize {
  const [sizes, setSizes] = useState(() => ({
    width: typeof window !== "undefined" ? window.innerWidth : 0,
    height: typeof window !== "undefined" ? window.innerHeight : 0,
  }));

  const handleResize = useCallback(() => {
    setSizes({
      width: window.innerWidth,
      height: window.innerHeight,
    });
  }, []);

  const isMounted = useOnMount(() => {
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  });

  const isMobile = sizes.width <= MOBILE_SIDEBAR_BREAKPOINT_PX;
  const isSmall = sizes.width <= DESKTOP_SMALL_BREAKPOINT_PX;

  return {
    height: sizes.height,
    width: sizes.width,
    isMobile: isMounted && isMobile,
    isSmallScreen: isMounted && isSmall,
  };
}
