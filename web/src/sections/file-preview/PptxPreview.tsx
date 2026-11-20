"use client";

import {
  memo,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { useDirection } from "@radix-ui/react-direction";
import { useFormatter, useTranslations } from "next-intl";
import { OnyxLoader, SelectCard, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { renderPptx } from "@/lib/pptx/renderPptx";
import {
  DocumentToolbar,
  PreviewSidebar,
} from "@/sections/file-preview/PreviewControls";

// The slide list's starting width, and its padding and the card's around a
// slide, as Craft's
const SLIDE_LIST_WIDTH = 112;
const SLIDE_INSET = 24;

interface SlideProps {
  // Sanitized slide markup from `renderPptx`
  html: string;
  // A thumbnail fits this width; without it, the slide fits its box
  width?: number;
}

/**
 * One slide in its own shadow root, scaled from the deck's slide size: to a
 * thumbnail's width, or to fit its box, centered.
 */
const Slide = memo(function Slide({ html, width }: SlideProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const [slideSize, setSlideSize] = useState({ width: 0, height: 0 });
  const [boxSize, setBoxSize] = useState({ width: 0, height: 0 });

  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const root = host.shadowRoot ?? host.attachShadow({ mode: "open" });
    root.innerHTML = html;
    const slide = root.firstElementChild;
    if (slide instanceof HTMLElement)
      setSlideSize({ width: slide.offsetWidth, height: slide.offsetHeight });
  }, [html]);

  useEffect(() => {
    const box = boxRef.current;
    if (!box || width !== undefined) return;
    const observer = new ResizeObserver(([entry]) => {
      // A hidden tab reports no size; keep the last one
      if (entry && entry.contentRect.width > 0)
        setBoxSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
    });
    observer.observe(box);
    return () => observer.disconnect();
  }, [width]);

  const measured = slideSize.width > 0 && slideSize.height > 0;
  const scale = !measured
    ? 0
    : width !== undefined
      ? width / slideSize.width
      : Math.min(
          boxSize.width / slideSize.width,
          boxSize.height / slideSize.height
        );
  const shownWidth = slideSize.width * scale;
  const shownHeight = slideSize.height * scale;

  return (
    <div
      ref={boxRef}
      className={
        width === undefined
          ? "relative h-full w-full overflow-hidden"
          : "relative overflow-hidden rounded-04 bg-background-neutral-02"
      }
      style={width === undefined ? undefined : { width, height: shownHeight }}
    >
      <div
        ref={hostRef}
        className="absolute origin-top-left"
        style={{
          left: width === undefined ? (boxSize.width - shownWidth) / 2 : 0,
          top: width === undefined ? (boxSize.height - shownHeight) / 2 : 0,
          transform: `scale(${scale})`,
          visibility: measured ? "visible" : "hidden",
        }}
      />
    </div>
  );
});

interface PptxPreviewProps {
  bytes: Uint8Array<ArrayBuffer>;
  // The deck does not parse
  onError: () => void;
}

/**
 * A PowerPoint deck as Craft shows one: a toolbar with the slide arrows, a
 * resizable slide list, and the active slide fit to the preview. The arrow
 * keys on the list move between slides. `renderPptx` parses the deck in the
 * browser and sanitizes each slide.
 */
export function PptxPreview({ bytes, onError }: PptxPreviewProps) {
  const t = useTranslations("chat.filePreview");
  const format = useFormatter();
  const rtl = useDirection() === "rtl";
  const [slides, setSlides] = useState<string[] | null>(null);
  const [current, setCurrent] = useState(0);
  const [showThumbnails, setShowThumbnails] = useState(true);
  const selectedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    renderPptx(bytes.buffer)
      .then((rendered) => {
        if (!cancelled) setSlides(rendered);
      })
      .catch(() => {
        if (!cancelled) onError();
      });
    return () => {
      cancelled = true;
    };
  }, [bytes, onError]);

  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "nearest" });
  }, [current]);

  if (slides === null)
    return (
      <Section>
        <OnyxLoader size={32} />
      </Section>
    );
  if (slides.length === 0)
    return (
      <Section padding={8}>
        <Text as="p" font="secondary-body" color="text-03">
          {t("pptx.empty.label")}
        </Text>
      </Section>
    );

  const count = slides.length;
  const select = (index: number) =>
    setCurrent(Math.max(0, Math.min(count - 1, index)));
  const counter = (index: number) =>
    t("pptx.slide.counter", {
      current: format.number(index + 1),
      total: format.number(count),
    });
  const moveWithKeys = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.defaultPrevented) return;
    const back = rtl ? "ArrowRight" : "ArrowLeft";
    const forward = rtl ? "ArrowLeft" : "ArrowRight";
    if (event.key === "ArrowUp" || event.key === back) {
      event.preventDefault();
      select(current - 1);
    } else if (event.key === "ArrowDown" || event.key === forward) {
      event.preventDefault();
      select(current + 1);
    }
  };

  return (
    <Section gap={0} justifyContent="start" alignItems="stretch">
      <DocumentToolbar
        label={t("pptx.controls.label")}
        thumbnailsLabel={t("pptx.thumbnails.toggle")}
        previousLabel={t("pptx.previous.label")}
        nextLabel={t("pptx.next.label")}
        counter={counter(current)}
        page={current + 1}
        pageCount={count}
        showThumbnails={showThumbnails}
        onToggleThumbnails={() => setShowThumbnails((value) => !value)}
        onPageChange={(page) => select(page - 1)}
      />
      <Section
        flexDirection="row"
        alignItems="stretch"
        gap={0}
        className="overflow-hidden"
      >
        <PreviewSidebar
          label={t("pptx.thumbnails.resize")}
          initialWidth={SLIDE_LIST_WIDTH}
          hidden={!showThumbnails}
        >
          {(width) => (
            <div
              role="toolbar"
              aria-label={t("pptx.slides.label")}
              aria-orientation="vertical"
              tabIndex={0}
              onKeyDown={moveWithKeys}
              className="h-full overflow-y-auto overscroll-contain p-2"
            >
              <Section gap={2} height="auto">
                {slides.map((html, index) => (
                  <SelectCard
                    key={index}
                    ref={index === current ? selectedRef : undefined}
                    role="button"
                    tabIndex={0}
                    aria-label={counter(index)}
                    aria-current={index === current ? "true" : undefined}
                    state={index === current ? "selected" : "empty"}
                    padding={1}
                    rounding={2}
                    onClick={() => select(index)}
                  >
                    <Section gap={1} height="auto" alignItems="start">
                      <Slide
                        html={html}
                        width={Math.max(40, width - SLIDE_INSET)}
                      />
                      <Text font="secondary-body" color="text-03">
                        {format.number(index + 1)}
                      </Text>
                    </Section>
                  </SelectCard>
                ))}
              </Section>
            </div>
          )}
        </PreviewSidebar>
        <div
          role="region"
          aria-label={counter(current)}
          className="min-w-0 flex-1 p-4"
        >
          <Slide html={slides[current] ?? ""} />
        </div>
      </Section>
    </Section>
  );
}
