"use client";

import {
  useState,
  useEffect,
  useCallback,
  useRef,
  type KeyboardEvent,
} from "react";
import { useFormatter, useTranslations } from "next-intl";
import { useFilePreview } from "@/lib/build/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import { cn } from "@opal/utils";
import { Button, SelectCard, Text } from "@opal/components";
import { SvgChevronLeft, SvgChevronRight, SvgFileText } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import {
  fetchPptxPreview,
  buildArtifactUrl,
} from "@/app/craft/services/apiServices";

interface PptxPreviewProps {
  sessionId: string;
  filePath: string;
  revision?: string;
  refreshKey?: number;
  isActive?: boolean;
}

/**
 * PptxPreview - Displays PowerPoint files as navigable slide images.
 * Triggers on-demand conversion via the backend, then renders
 * individual slide JPEGs in a carousel with keyboard navigation.
 */
export default function PptxPreview({
  sessionId,
  filePath,
  revision,
  refreshKey,
  isActive = true,
}: PptxPreviewProps) {
  const t = useTranslations("craft.pptxPreview");
  const format: ReturnType<typeof useFormatter> = useFormatter();
  const selectedThumbnailRef = useRef<HTMLDivElement>(null);
  const [currentSlide, setCurrentSlide] = useState(0);
  const [imageLoading, setImageLoading] = useState(true);

  const { data, error, isLoading } = useFilePreview(
    SWR_KEYS.buildSessionPptxPreview(sessionId, filePath),
    async () => ({
      ...(await fetchPptxPreview(sessionId, filePath)),
      imageRevision: crypto.randomUUID(),
    }),
    revision,
    refreshKey,
    isActive
  );

  const slideCount = data?.slide_count ?? 0;
  const activeSlide = Math.min(currentSlide, Math.max(0, slideCount - 1));

  // An updated deck can have fewer slides than the current selection.
  useEffect(() => {
    if (data) {
      setCurrentSlide((index) =>
        Math.min(index, Math.max(0, data.slide_count - 1))
      );
    }
  }, [data]);

  const goToPrev = useCallback(() => {
    setCurrentSlide((prev) => Math.max(0, prev - 1));
  }, []);

  const goToNext = useCallback(() => {
    if (slideCount === 0) return;
    setCurrentSlide((prev) => Math.min(slideCount - 1, prev + 1));
  }, [slideCount]);

  // Reset slide index when file changes
  useEffect(() => {
    setCurrentSlide(0);
  }, [filePath]);

  // Reset image loading state when slide changes
  useEffect(() => {
    setImageLoading(true);
  }, [currentSlide, data]);

  useEffect(() => {
    if (isActive) {
      selectedThumbnailRef.current?.scrollIntoView({
        block: "nearest",
        inline: "nearest",
      });
    }
  }, [activeSlide, data?.imageRevision, isActive]);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!isActive || event.defaultPrevented) return;
    // Horizontal arrows follow the reading direction.
    const isRtl = document.documentElement.dir === "rtl";
    if (
      event.key === "ArrowUp" ||
      event.key === (isRtl ? "ArrowRight" : "ArrowLeft")
    ) {
      event.preventDefault();
      goToPrev();
    } else if (
      event.key === "ArrowDown" ||
      event.key === (isRtl ? "ArrowLeft" : "ArrowRight")
    ) {
      event.preventDefault();
      goToNext();
    }
  }

  if (isLoading) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={8}
      >
        <Text font="secondary-body" color="text-03">
          {t("converting.label")}
        </Text>
      </Section>
    );
  }

  if (error) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={8}
      >
        <SvgFileText size={48} className="stroke-text-02" />
        <Text font="heading-h3" color="text-03">
          {t("error.title")}
        </Text>
        <div className="text-center max-w-md">
          <Text font="secondary-body" color="text-02">
            {error.message}
          </Text>
        </div>
      </Section>
    );
  }

  if (!data || slideCount === 0) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={8}
      >
        <SvgFileText size={48} className="stroke-text-02" />
        <Text font="secondary-body" color="text-03">
          {t("empty.label")}
        </Text>
      </Section>
    );
  }

  const slidePath = data.slide_paths[activeSlide] ?? "";
  // Local refresh counters can repeat after reloads; each response needs fresh images.
  const slideUrl = `${buildArtifactUrl(sessionId, slidePath)}?revision=${data.imageRevision}`;

  return (
    <div className="h-full min-h-0 flex overflow-hidden">
      <div
        role="toolbar"
        aria-label={t("slides.label")}
        aria-orientation="vertical"
        tabIndex={0}
        onKeyDown={handleKeyDown}
        className="w-28 shrink-0 overflow-y-auto overscroll-contain border-e border-border-02 p-2"
      >
        <div className="flex flex-col gap-2">
          {data.slide_paths.map((path, index) => (
            <SelectCard
              key={path}
              ref={index === activeSlide ? selectedThumbnailRef : undefined}
              role="button"
              tabIndex={0}
              aria-label={t("slide.counter", {
                current: index + 1,
                total: slideCount,
              })}
              aria-current={index === activeSlide ? "true" : undefined}
              state={index === activeSlide ? "selected" : "empty"}
              padding={1}
              rounding={2}
              onClick={() => setCurrentSlide(index)}
            >
              <div className="flex flex-col gap-1">
                <img
                  src={`${buildArtifactUrl(sessionId, path)}?revision=${data.imageRevision}`}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  className="w-full aspect-video object-contain rounded-04 bg-background-neutral-02"
                />
                <Text font="secondary-body" color="text-03">
                  {format.number(index + 1)}
                </Text>
              </div>
            </SelectCard>
          ))}
        </div>
      </div>
      <div className="min-w-0 flex-1 flex flex-col overflow-hidden">
        <div className="relative flex-1 flex items-center justify-center p-4 overflow-hidden">
          {imageLoading && (
            <div className="absolute">
              <Text font="secondary-body" color="text-03">
                {t("loadingSlide.label")}
              </Text>
            </div>
          )}
          <img
            src={slideUrl}
            alt={t("slide.counter", {
              current: activeSlide + 1,
              total: slideCount,
            })}
            className={cn(
              "max-w-full max-h-full object-contain transition-opacity",
              imageLoading ? "opacity-0" : "opacity-100"
            )}
            onLoad={() => setImageLoading(false)}
            onError={() => setImageLoading(false)}
          />
        </div>
        {slideCount > 1 && (
          <div className="flex items-center justify-center gap-3 p-2 border-t border-border-02">
            <Button
              icon={SvgChevronLeft}
              prominence="tertiary"
              size="sm"
              aria-label={t("previous.label")}
              onClick={goToPrev}
              disabled={activeSlide === 0}
            />
            <Text font="secondary-body" color="text-03">
              {t("slide.counter", {
                current: activeSlide + 1,
                total: slideCount,
              })}
            </Text>
            <Button
              icon={SvgChevronRight}
              prominence="tertiary"
              size="sm"
              aria-label={t("next.label")}
              onClick={goToNext}
              disabled={activeSlide === slideCount - 1}
            />
          </div>
        )}
      </div>
    </div>
  );
}
