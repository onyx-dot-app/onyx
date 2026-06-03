"use client";

import { useState, useCallback } from "react";
import useOnMount from "@opal/hooks/useOnMount";
import {
  MOBILE_SIDEBAR_BREAKPOINT_PX,
  DESKTOP_MEDIUM_BREAKPOINT_PX,
} from "@opal/constants";

export interface ScreenSize {
  width: number;
  height: number;
  isMobile: boolean;
  isMediumScreen: boolean;
}

export default function useScreenSize(): ScreenSize {
  const [sizes, setSizes] = useState(() => ({
    width: typeof window !== "undefined" ? window.innerWidth : 0,
    height: typeof window !== "undefined" ? window.innerHeight : 0,
  }));

  const handleResize = useCallback(() => {
    setSizes({ width: window.innerWidth, height: window.innerHeight });
  }, []);

  const isMounted = useOnMount(() => {
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  });

  return {
    width: sizes.width,
    height: sizes.height,
    isMobile: isMounted && sizes.width <= MOBILE_SIDEBAR_BREAKPOINT_PX,
    isMediumScreen: isMounted && sizes.width <= DESKTOP_MEDIUM_BREAKPOINT_PX,
  };
}
