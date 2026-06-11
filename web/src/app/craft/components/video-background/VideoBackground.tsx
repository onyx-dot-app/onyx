"use client";

import { useBuildContext } from "@/app/craft/contexts/BuildContext";
import { VIDEO_BACKGROUND_SRC } from "@/app/craft/components/video-background/constants";

export default function VideoBackground() {
  const { videoBackgroundEnabled } = useBuildContext();

  if (!videoBackgroundEnabled) return null;

  return (
    <video
      autoPlay
      loop
      muted
      playsInline
      className="absolute inset-0 w-full h-full object-cover z-0 pointer-events-none opacity-30 blur-sm"
    >
      <source src={VIDEO_BACKGROUND_SRC} type="video/mp4" />
    </video>
  );
}
