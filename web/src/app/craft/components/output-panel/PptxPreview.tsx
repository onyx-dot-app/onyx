"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useFormatter, useTranslations } from "next-intl";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { cn } from "@opal/utils";
import { Button, SelectCard, Text } from "@opal/components";
import { SvgChevronLeft, SvgChevronRight, SvgFileText } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { fetchPptxPreview } from "@/app/craft/services/apiServices";
import { getArtifactUrl } from "@/lib/build/client";

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

  const { data, error, isLoading } = useSWR(
    [
      SWR_KEYS.buildSessionPptxPreview(sessionId, filePath),
      revision,
      refreshKey ?? 0,
    ],
    async () => ({
      ...(await fetchPptxPreview(sessionId, filePath)),
      imageRevision: crypto.randomUUID(),
    }),
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: revision === undefined,
      dedupingInterval: 10000,
    }
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

  // Keyboard navigation
  useEffect(() => {
    if (!isActive) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (
        e.defaultPrevented ||
        (e.target instanceof HTMLElement &&
          e.target.closest("input, textarea, select, [contenteditable='true']"))
      )
        return;
      // Horizontal arrows follow the reading direction, so RTL swaps them.
      const isRtl = document.documentElement.dir === "rtl";
      if (
        e.key === "ArrowUp" ||
        e.key === (isRtl ? "ArrowRight" : "ArrowLeft")
      ) {
        e.preventDefault();
        goToPrev();
      } else if (
        e.key === "ArrowDown" ||
        e.key === (isRtl ? "ArrowLeft" : "ArrowRight")
      ) {
        e.preventDefault();
        goToNext();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isActive, goToPrev, goToNext]);

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
  const slideUrl = `${getArtifactUrl(sessionId, slidePath)}?revision=${data.imageRevision}`;

  return (
    <div className="h-full min-h-0 flex overflow-hidden">
      <nav
        aria-label={t("slides.label")}
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
                  src={`${getArtifactUrl(sessionId, path)}?revision=${data.imageRevision}`}
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
      </nav>
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
