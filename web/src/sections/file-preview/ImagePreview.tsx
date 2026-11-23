"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgZoomIn, SvgZoomOut } from "@opal/icons";
import { cn } from "@opal/utils";
import FloatingFooter from "@/sections/file-preview/FloatingFooter";

interface ImagePreviewProps {
  src: string;
  fileName: string;
  // The footer's actions, after the size toggle. Without them, the image
  // shows fit, with no footer.
  actions?: ReactNode;
  // The browser cannot draw the image, as for HEIC or TIFF
  onError: () => void;
}

/**
 * An image, fit to the preview or, with a footer, at its own size in a
 * scrolling view.
 */
export function ImagePreview({
  src,
  fileName,
  actions,
  onError,
}: ImagePreviewProps) {
  const t = useTranslations("chat.filePreview");
  const [loaded, setLoaded] = useState(false);
  const [actualSize, setActualSize] = useState(false);

  return (
    <>
      <Section
        justifyContent={actualSize ? "start" : "center"}
        alignItems={actualSize ? "start" : "center"}
        padding={4}
        className="relative overflow-auto"
      >
        {!loaded && (
          <div className="absolute">
            <Text as="p" font="secondary-body" color="text-03">
              {t("image.loading.label")}
            </Text>
          </div>
        )}
        <img
          src={src}
          alt={fileName}
          className={cn(
            "rounded-08 transition-opacity",
            // At its own size, the margin scrolls the image's bottom clear of
            // the footer, as the Word and Markdown previews' bottom padding
            // does. Section has no bottom-only padding.
            actualSize
              ? "mb-12 max-w-none"
              : "max-h-full max-w-full object-contain",
            loaded ? "opacity-100" : "opacity-0"
          )}
          onLoad={() => setLoaded(true)}
          onError={onError}
        />
      </Section>
      {actions !== undefined && (
        <FloatingFooter
          left={
            loaded && (
              <div className="rounded-12 bg-background-tint-00 p-1 shadow-lg">
                <Button
                  prominence="tertiary"
                  size="sm"
                  icon={actualSize ? SvgZoomOut : SvgZoomIn}
                  aria-pressed={actualSize}
                  onClick={() => setActualSize((value) => !value)}
                >
                  {t("image.actualSize.label")}
                </Button>
              </div>
            )
          }
          right={actions}
        />
      )}
    </>
  );
}
