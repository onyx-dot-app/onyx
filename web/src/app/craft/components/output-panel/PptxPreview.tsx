"use client";

import {
  useState,
  useEffect,
  useEffectEvent,
  useRef,
  type KeyboardEvent,
} from "react";
import { useFormatter, useTranslations } from "next-intl";
import { useFilePreview } from "@/lib/build/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import { cn } from "@opal/utils";
import { SelectCard, Text } from "@opal/components";
import { SvgFileText } from "@opal/icons";
import DocumentPreviewControls from "@/app/craft/components/output-panel/DocumentPreviewControls";
import PreviewSidebar from "@/app/craft/components/output-panel/PreviewSidebar";
import { Section } from "@/layouts/general-layouts";
import {
  fetchPptxPreview,
  buildArtifactUrl,
} from "@/app/craft/services/apiServices";

interface PptxPreviewProps {
  onRefreshingChange?: (isRefreshing: boolean) => void;
  initialSlide?: number;
  onSlideChange?: (slide: number) => void;
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
  onRefreshingChange,
  initialSlide = 0,
  onSlideChange,
}: PptxPreviewProps) {
  const t = useTranslations("craft.pptxPreview");
  const format: ReturnType<typeof useFormatter> = useFormatter();
  const selectedThumbnailRef = useRef<HTMLDivElement>(null);
  const [currentSlide, setCurrentSlide] = useState(initialSlide);
  const [showThumbnails, setShowThumbnails] = useState(true);

  const { data, error, isLoading } = useFilePreview(
    SWR_KEYS.buildSessionPptxPreview(sessionId, filePath),
    async () => ({
      ...(await fetchPptxPreview(sessionId, filePath)),
      imageRevision: crypto.randomUUID(),
    }),
    { revision, refreshKey, isActive, onRefreshingChange }
  );

  const slideCount = data?.slide_count ?? 0;
  const activeSlide = Math.max(
    0,
    Math.min(currentSlide, Math.max(0, slideCount - 1))
  );

  // Keep the selection in bounds before rendering a replacement deck.
  if (data && currentSlide !== activeSlide) setCurrentSlide(activeSlide);

  useEffect(() => {
    if (isActive) {
      selectedThumbnailRef.current?.scrollIntoView({
        block: "nearest",
        inline: "nearest",
      });
    }
  }, [activeSlide, data?.imageRevision, isActive]);

  const hasSlides = slideCount > 0;
  const reportSlide = useEffectEvent(() => onSlideChange?.(activeSlide));
  // Persist accepted selection, including bounds changes after a deck replacement.
  useEffect(() => {
    if (hasSlides) reportSlide();
  }, [hasSlides, activeSlide]);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!isActive || event.defaultPrevented) return;
    // Horizontal arrows follow the reading direction.
    const isRtl = document.documentElement.dir === "rtl";
    if (
      event.key === "ArrowUp" ||
      event.key === (isRtl ? "ArrowRight" : "ArrowLeft")
    ) {
      event.preventDefault();
      setCurrentSlide((slide) => Math.max(0, slide - 1));
    } else if (
      event.key === "ArrowDown" ||
      event.key === (isRtl ? "ArrowLeft" : "ArrowRight")
    ) {
      event.preventDefault();
      setCurrentSlide((slide) =>
        Math.min(Math.max(0, slideCount - 1), slide + 1)
      );
    }
  }

  if (!data && isLoading && isActive) {
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

  if (error && !data) {
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
    <div className="relative h-full min-h-0 flex flex-col overflow-hidden">
      {error && (
        <div role="alert" className="shrink-0 px-3 py-2">
          <Text font="secondary-body" color="text-03">
            {t("error.title")}
          </Text>
        </div>
      )}
      <DocumentPreviewControls
        label={t("controls.label")}
        previousLabel={t("previous.label")}
        nextLabel={t("next.label")}
        thumbnailsLabel={t("thumbnails.toggle")}
        counter={t("slide.counter", {
          current: activeSlide + 1,
          total: slideCount,
        })}
        page={activeSlide + 1}
        pageCount={slideCount}
        showThumbnails={showThumbnails}
        onToggleThumbnails={() => setShowThumbnails((value) => !value)}
        onPageChange={(page) => setCurrentSlide(page - 1)}
      />
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <PreviewSidebar
          hidden={!showThumbnails}
          label={t("resize.ariaLabel")}
          initialWidth={112}
        >
          <div
            role="toolbar"
            aria-label={t("slides.label")}
            aria-orientation="vertical"
            tabIndex={0}
            onKeyDown={handleKeyDown}
            className="h-full overflow-y-auto overscroll-contain p-2"
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
        </PreviewSidebar>
        <div className="min-w-0 flex-1 flex flex-col overflow-hidden">
          <SlideImage
            key={slideUrl}
            src={slideUrl}
            alt={t("slide.counter", {
              current: activeSlide + 1,
              total: slideCount,
            })}
          />
        </div>
      </div>
    </div>
  );
}

interface SlideImageProps {
  src: string;
  alt: string;
}

function SlideImage({ src, alt }: SlideImageProps) {
  const t = useTranslations("craft.pptxPreview");
  const [status, setStatus] = useState<"loading" | "loaded" | "failed">(
    "loading"
  );
  return (
    <div className="relative flex-1 flex items-center justify-center p-4 overflow-hidden">
      {status === "loading" && (
        <div className="absolute">
          <Text font="secondary-body" color="text-03">
            {t("loadingSlide.label")}
          </Text>
        </div>
      )}
      {status === "failed" ? (
        <Text font="secondary-body" color="text-03">
          {t("error.title")}
        </Text>
      ) : (
        <img
          src={src}
          alt={alt}
          className={cn(
            "max-w-full max-h-full object-contain transition-opacity",
            status === "loading" ? "opacity-0" : "opacity-100"
          )}
          onLoad={() => setStatus("loaded")}
          onError={() => setStatus("failed")}
        />
      )}
    </div>
  );
}
