import { MOBILE_SIDEBAR_BREAKPOINT_PX } from "@/lib/constants";
import { useEffect } from "react";
import { useState } from "react";

export interface ScreenSize {
  height: number;
  width: number;
  isMobile: boolean;
}

export default function useScreenSize(): ScreenSize {
  const [sizes, setSizes] = useState({
    width: 0,
    height: 0,
  });

  function handleResize() {
    setSizes({
      width: window.innerWidth,
      height: window.innerHeight,
    });
  }

  useEffect(() => {
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const isMobile = sizes.width <= MOBILE_SIDEBAR_BREAKPOINT_PX;

  return {
    height: sizes.height,
    width: sizes.width,
    isMobile,
  };
}
