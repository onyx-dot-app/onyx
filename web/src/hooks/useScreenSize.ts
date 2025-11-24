"use client";

import { MOBILE_SIDEBAR_BREAKPOINT_PX } from "@/lib/constants";
import { useState } from "react";
import useIsMounted from "./useIsMounted";

export interface ScreenSize {
  height: number;
  width: number;
  isMobile: boolean;
}

export default function useScreenSize(): ScreenSize {
  const [sizes, setSizes] = useState(() => ({
    width: typeof window !== "undefined" ? window.innerWidth : 0,
    height: typeof window !== "undefined" ? window.innerHeight : 0,
  }));

  function handleResize() {
    setSizes({
      width: window.innerWidth,
      height: window.innerHeight,
    });
  }

  const isMounted = useIsMounted(() => {
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  });

  const isMobile = sizes.width <= MOBILE_SIDEBAR_BREAKPOINT_PX;

  return {
    height: sizes.height,
    width: sizes.width,
    isMobile: isMounted ? isMobile : false,
  };
}
