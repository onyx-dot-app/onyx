"use client";

import { useEffect, useState, useMemo } from "react";
import { cn } from "@/lib/utils";

interface RecordingWaveformProps {
  isRecording: boolean;
  isMuted?: boolean;
}

function RecordingWaveform({
  isRecording,
  isMuted = false,
}: RecordingWaveformProps) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  // Reset and start timer when recording starts
  useEffect(() => {
    if (!isRecording) {
      setElapsedSeconds(0);
      return;
    }

    const interval = setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);

    return () => clearInterval(interval);
  }, [isRecording]);

  // Format time as MM:SS
  const formattedTime = useMemo(() => {
    const minutes = Math.floor(elapsedSeconds / 60);
    const seconds = elapsedSeconds % 60;
    return `${minutes.toString().padStart(2, "0")}:${seconds
      .toString()
      .padStart(2, "0")}`;
  }, [elapsedSeconds]);

  // Generate random bar heights for waveform animation
  const bars = useMemo(() => {
    return Array.from({ length: 50 }, (_, i) => ({
      id: i,
      // Create a wave pattern with some randomness
      baseHeight: Math.sin(i * 0.3) * 6 + 8,
      delay: i * 0.02,
    }));
  }, []);

  if (!isRecording) {
    return null;
  }

  return (
    <div className="flex items-center gap-3 px-3 py-2 bg-background-tint-00 rounded-12 min-h-[32px]">
      {/* Waveform visualization */}
      <div className="flex-1 flex items-center justify-center gap-[2px] h-4 overflow-hidden">
        {bars.map((bar) => (
          <div
            key={bar.id}
            className={cn(
              "w-[2px] bg-text-03 rounded-full",
              !isMuted && "animate-waveform"
            )}
            style={{
              // When muted, show flat bars (2px height), otherwise animate with base height
              height: isMuted ? "2px" : `${bar.baseHeight}px`,
              animationDelay: isMuted ? undefined : `${bar.delay}s`,
            }}
          />
        ))}
      </div>

      {/* Timer */}
      <span className="font-mono text-xs text-text-03 tabular-nums shrink-0">
        {formattedTime}
      </span>
    </div>
  );
}

export default RecordingWaveform;
