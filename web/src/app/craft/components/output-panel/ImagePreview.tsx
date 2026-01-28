"use client";

import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { SvgImage } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";

interface ImagePreviewProps {
  src: string;
  fileName: string;
}

/**
 * ImagePreview - Displays images with loading and error states
 * Includes proper accessibility attributes
 */
export default function ImagePreview({ src, fileName }: ImagePreviewProps) {
  const [imageLoading, setImageLoading] = useState(true);
  const [imageError, setImageError] = useState(false);

  // Extract just the filename from path for better alt text
  const displayName = fileName.split("/").pop() || fileName;

  // Reset loading state when src changes
  useEffect(() => {
    setImageLoading(true);
    setImageError(false);
  }, [src]);

  if (imageError) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <SvgImage size={48} className="stroke-text-02" />
        <Text headingH3 text03>
          Failed to load image
        </Text>
        <Text secondaryBody text02>
          The image could not be displayed
        </Text>
      </Section>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex-1 flex items-center justify-center p-4">
        {imageLoading && (
          <div className="absolute">
            <Text secondaryBody text03>
              Loading image...
            </Text>
          </div>
        )}
        <img
          src={src}
          alt={displayName}
          role="img"
          aria-label={`Preview of ${displayName}`}
          className={cn(
            "max-w-full max-h-full object-contain transition-opacity",
            imageLoading ? "opacity-0" : "opacity-100"
          )}
          onLoad={() => setImageLoading(false)}
          onError={() => {
            setImageLoading(false);
            setImageError(true);
          }}
        />
      </div>
    </div>
  );
}
