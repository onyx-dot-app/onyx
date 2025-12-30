"use client";

import dynamic from "next/dynamic";

const StatsOverlay = dynamic(() => import("@/components/dev/StatsOverlay"), {
  ssr: false,
});

export default function StatsOverlayLoader() {
  return <StatsOverlay />;
}
