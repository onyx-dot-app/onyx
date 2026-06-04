"use client";

import { useEffect, useState } from "react";

export default function useOnMount(f?: React.EffectCallback): boolean {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    return f?.();
  }, []);

  return mounted;
}
