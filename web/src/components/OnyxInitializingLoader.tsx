"use client";

import Logo from "@/refresh-components/Logo";
import { useSettings } from "@/lib/settings/hooks";

export default function OnyxInitializingLoader() {
  const { appName } = useSettings();

  return (
    <div className="mx-auto my-auto animate-pulse">
      <Logo folded size={96} className="mx-auto mb-3" />
      <p className="text-lg text-text font-semibold">Initializing {appName}</p>
    </div>
  );
}
