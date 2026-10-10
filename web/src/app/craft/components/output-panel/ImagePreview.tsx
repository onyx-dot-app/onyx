"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@opal/utils";
import { Button, Text } from "@opal/components";
import { SvgImage } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";

interface ImagePreviewProps {
  src: string;
  fileName: string;
}

export default function ImagePreview({ src, fileName }: ImagePreviewProps) {
  const t = useTranslations("craft.imagePreview");
  const [imageLoading, setImageLoading] = useState(true);
  const [imageError, setImageError] = useState(false);
  const [contrastBackground, setContrastBackground] = useState(true);

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
        padding={8}
      >
        <SvgImage size={48} className="stroke-text-02" />
        <Text font="heading-h3" color="text-03">
          {t("error.title")}
        </Text>
        <Text font="secondary-body" color="text-02">
          {t("error.description")}
        </Text>
      </Section>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex justify-end px-4 pt-3">
        <Button
          prominence={contrastBackground ? "secondary" : "tertiary"}
          size="xs"
          aria-pressed={contrastBackground}
          onClick={() => setContrastBackground((value) => !value)}
        >
          {t("background.contrast")}
        </Button>
      </div>
      <div className="relative min-h-0 flex-1 flex items-center justify-center p-4">
        {imageLoading && (
          <div className="absolute">
            <Text font="secondary-body" color="text-03">
              {t("loading.label")}
            </Text>
          </div>
        )}
        <img
          src={src}
          alt={displayName}

          aria-label={t("preview.ariaLabel", { name: displayName })}
          className={cn(
            "max-w-full max-h-full object-contain rounded-md transition-opacity",
            contrastBackground && "bg-background-neutral-inverted-04",
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
