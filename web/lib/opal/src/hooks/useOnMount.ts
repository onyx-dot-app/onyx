"use client";

import { useEffect, useState } from "react";

export default function useOnMount(f?: React.EffectCallback): boolean {
  const [mounted, setMounted] = useState(false);

  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- marks the client mount so callers render browser-only content after hydration, and runs the caller's mount callback
  useEffect(() => {
    setMounted(true);
    return f?.();
  }, []);

  return mounted;
}
