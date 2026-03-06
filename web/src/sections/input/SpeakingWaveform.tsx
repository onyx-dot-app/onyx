"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@opal/components";
import { SvgVolume, SvgVolumeOff } from "@opal/icons";

interface SpeakingWaveformProps {
  isSpeaking: boolean;
  onMuteToggle?: () => void;
  isMuted?: boolean;
}

function SpeakingWaveform({
  isSpeaking,
  onMuteToggle,
  isMuted = false,
}: SpeakingWaveformProps) {
  // Generate bar pattern for waveform animation - matching the Figma design
  // Figma shows ~30 bars in a 120px width area
  const bars = useMemo(() => {
    return Array.from({ length: 28 }, (_, i) => ({
      id: i,
      // Create a natural wave pattern with more height variation like in Figma
      baseHeight: Math.sin(i * 0.4) * 5 + 8,
      delay: i * 0.025,
    }));
  }, []);

  if (!isSpeaking) {
    return null;
  }

  return (
    <div className="flex items-center gap-0.5 p-1.5 bg-background-tint-00 rounded-16 shadow-01">
      {/* Waveform container - matches Figma's max-w-[144px] min-h-[32px] */}
      <div className="flex items-center p-1 bg-background-tint-00 rounded-12 max-w-[144px] min-h-[32px]">
        <div className="flex items-center p-1">
          {/* Waveform - 120px width, 16px height as per Figma */}
          <div className="flex items-center justify-center gap-[2px] h-4 w-[120px] overflow-hidden">
            {bars.map((bar) => (
              <div
                key={bar.id}
                className={cn(
                  "w-[3px] rounded-full",
                  isMuted ? "bg-text-03" : "bg-theme-blue-05",
                  !isMuted && "animate-waveform"
                )}
                style={{
                  height: isMuted ? "2px" : `${bar.baseHeight}px`,
                  animationDelay: isMuted ? undefined : `${bar.delay}s`,
                }}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Divider - 2px width, full height of container */}
      <div className="w-0.5 self-stretch bg-border-02" />

      {/* Volume button */}
      {onMuteToggle && (
        <div className="flex items-center p-1 bg-background-tint-00 rounded-12">
          <Button
            icon={isMuted ? SvgVolumeOff : SvgVolume}
            onClick={onMuteToggle}
            prominence="tertiary"
            size="sm"
            tooltip={isMuted ? "Unmute" : "Mute"}
          />
        </div>
      )}
    </div>
  );
}

export default SpeakingWaveform;
