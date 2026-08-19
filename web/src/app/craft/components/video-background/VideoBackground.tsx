"use client";

import { useBuildContext } from "@/app/craft/contexts/BuildContext";
import { VIDEO_BACKGROUND_SRC } from "@/app/craft/components/video-background/constants";

export default function VideoBackground() {
  const { videoBackgroundEnabled } = useBuildContext();

  if (!videoBackgroundEnabled) return null;

  return (
    <div
      aria-hidden="true"
      className="absolute inset-0 z-0 overflow-hidden pointer-events-none"
    >
      {/* scale-105 crops the transparent fringe the blur creates at the edges */}
      <video
        autoPlay
        loop
        muted
        playsInline
        className="w-full h-full object-cover scale-105 blur-xs"
      >
        <source src={VIDEO_BACKGROUND_SRC} type="video/mp4" />
      </video>
      {/* tint overlay keeps foreground readable without washing the video out */}
      <div className="absolute inset-0 bg-background-tint-00/60" />
    </div>
  );
}
