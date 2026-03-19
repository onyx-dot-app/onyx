"use client";

import { useEffect, useState, useMemo, useRef } from "react";
import { cn } from "@/lib/utils";
import { formatElapsedTime } from "@/lib/dateUtils";
import { Button } from "@opal/components";
import {
  SvgMicrophone,
  SvgMicrophoneOff,
  SvgVolume,
  SvgVolumeOff,
} from "@opal/icons";

// Recording waveform constants
const RECORDING_BAR_COUNT = 120;
const MIN_BAR_HEIGHT = 2;
const MAX_BAR_HEIGHT = 16;

// Speaking waveform constants
const SPEAKING_BAR_COUNT = 28;

interface WaveformProps {
  /** Visual style and behavior variant */
  variant: "speaking" | "recording";
  /** Whether the waveform is actively animating */
  isActive: boolean;
  /** Whether audio is muted */
  isMuted?: boolean;
  /** Current microphone audio level (0-1), only used for recording variant */
  audioLevel?: number;
  /** Callback when mute button is clicked */
  onMuteToggle?: () => void;
}

function Waveform({
  variant,
  isActive,
  isMuted = false,
  audioLevel = 0,
  onMuteToggle,
}: WaveformProps) {
  // ─── Recording variant state ───────────────────────────────────────────────
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [barHeights, setBarHeights] = useState<number[]>(
    () => new Array(RECORDING_BAR_COUNT).fill(MIN_BAR_HEIGHT) as number[]
  );
  const animationRef = useRef<number | null>(null);
  const lastPushTimeRef = useRef(0);
  const audioLevelRef = useRef(audioLevel);
  audioLevelRef.current = audioLevel;

  // ─── Speaking variant bars ─────────────────────────────────────────────────
  const speakingBars = useMemo(() => {
    return Array.from({ length: SPEAKING_BAR_COUNT }, (_, i) => ({
      id: i,
      // Create a natural wave pattern with height variation
      baseHeight: Math.sin(i * 0.4) * 5 + 8,
      delay: i * 0.025,
    }));
  }, []);

  // ─── Recording: Timer effect ───────────────────────────────────────────────
  useEffect(() => {
    if (variant !== "recording") return;

    if (!isActive) {
      setElapsedSeconds(0);
      return;
    }

    const interval = setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);

    return () => clearInterval(interval);
  }, [variant, isActive]);

  // ─── Recording: Audio level visualization effect ───────────────────────────
  useEffect(() => {
    if (variant !== "recording") return;

    if (!isActive) {
      setBarHeights(
        new Array(RECORDING_BAR_COUNT).fill(MIN_BAR_HEIGHT) as number[]
      );
      lastPushTimeRef.current = 0;
      return;
    }

    const updateBars = (timestamp: number) => {
      // Push a new bar roughly every 50ms (~20fps scrolling)
      if (timestamp - lastPushTimeRef.current >= 50) {
        lastPushTimeRef.current = timestamp;
        const level = isMuted ? 0 : audioLevelRef.current;
        const height =
          MIN_BAR_HEIGHT + level * (MAX_BAR_HEIGHT - MIN_BAR_HEIGHT);

        setBarHeights((prev) => {
          const next = prev.slice(1);
          next.push(height);
          return next;
        });
      }

      animationRef.current = requestAnimationFrame(updateBars);
    };

    animationRef.current = requestAnimationFrame(updateBars);

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
        animationRef.current = null;
      }
    };
  }, [variant, isActive, isMuted]);

  const formattedTime = useMemo(
    () => formatElapsedTime(elapsedSeconds),
    [elapsedSeconds]
  );

  if (!isActive) {
    return null;
  }

  // ─── Speaking variant render ───────────────────────────────────────────────
  if (variant === "speaking") {
    return (
      <div className="flex items-center gap-0.5 p-1.5 bg-background-tint-00 rounded-16 shadow-01">
        {/* Waveform container */}
        <div className="flex items-center p-1 bg-background-tint-00 rounded-12 max-w-[144px] min-h-[32px]">
          <div className="flex items-center p-1">
            {/* Waveform bars */}
            <div className="flex items-center justify-center gap-[2px] h-4 w-[120px] overflow-hidden">
              {speakingBars.map((bar) => (
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

        {/* Divider */}
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

  // ─── Recording variant render ──────────────────────────────────────────────
  return (
    <div className="flex items-center gap-3 px-3 py-2 bg-background-tint-00 rounded-12 min-h-[32px]">
      {/* Waveform visualization driven by real audio levels */}
      <div className="flex-1 flex items-center justify-between h-4 overflow-hidden">
        {barHeights.map((height, i) => (
          <div
            key={i}
            className="w-[1.5px] bg-text-03 rounded-full shrink-0 transition-[height] duration-75"
            style={{ height: `${height}px` }}
          />
        ))}
      </div>

      {/* Timer */}
      <span className="font-mono text-xs text-text-03 tabular-nums shrink-0">
        {formattedTime}
      </span>

      {/* Mute button */}
      {onMuteToggle && (
        <Button
          icon={isMuted ? SvgMicrophoneOff : SvgMicrophone}
          onClick={onMuteToggle}
          prominence="tertiary"
          size="sm"
          aria-label={isMuted ? "Unmute microphone" : "Mute microphone"}
        />
      )}
    </div>
  );
}

export default Waveform;
