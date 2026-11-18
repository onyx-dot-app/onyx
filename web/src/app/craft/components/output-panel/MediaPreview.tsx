"use client";

/* eslint-disable jsx-a11y/media-has-caption -- Artifact files do not include a caption track. */

import { useEffect, useRef, useState } from "react";
import { Section } from "@opal/layouts";

interface MediaPreviewProps {
  blob: Blob;
  kind: "audio" | "video";
  fileName: string;
  isActive: boolean;
  onError: () => void;
}

export default function MediaPreview({
  blob,
  kind,
  fileName,
  isActive,
  onError,
}: MediaPreviewProps) {
  const [source, setSource] = useState<{ blob: Blob; url: string }>();
  const media = useRef<HTMLMediaElement | null>(null);
  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- creates the media object URL and revokes it, pausing playback, on change
  useEffect(() => {
    const url = URL.createObjectURL(blob);
    setSource({ blob, url });
    return () => {
      media.current?.pause();
      URL.revokeObjectURL(url);
    };
  }, [blob]);
  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- pauses the media element when its tab is hidden
  useEffect(() => {
    if (!isActive) media.current?.pause();
  }, [isActive]);
  if (source?.blob !== blob) return null;
  const props = {
    src: source.url,
    controls: true,
    "aria-label": fileName,
    onError,
    ref: (element: HTMLMediaElement | null) => {
      media.current = element;
    },
    className: "max-h-full w-full",
  };
  return (
    <Section padding={4}>
      {kind === "audio" ? (
        <audio {...props} />
      ) : (
        <video {...props} playsInline />
      )}
    </Section>
  );
}
