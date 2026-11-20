"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { OnyxLoader, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { renderDocx } from "@/lib/docx/renderDocx";
import FloatingFooter from "@/sections/file-preview/FloatingFooter";

interface DocxPreviewProps {
  bytes: Uint8Array<ArrayBuffer>;
  // The footer's actions: before the document renders, and for its text
  download: ReactNode;
  textActions: (text: string) => ReactNode;
  onError: () => void;
}

/**
 * A Word document as pages scaled to the preview's width, with its word
 * count. `renderDocx` sanitizes the markup off-screen, and the pages render
 * in a shadow root, so the document's styles stay inside it. The pages lay
 * out once at their own width; a change of width only scales them.
 */
export function DocxPreview({
  bytes,
  download,
  textActions,
  onError,
}: DocxPreviewProps) {
  const t = useTranslations("chat.filePreview");
  const scroller = useRef<HTMLDivElement>(null);
  const sizer = useRef<HTMLDivElement>(null);
  const host = useRef<HTMLDivElement>(null);
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    const view = scroller.current;
    const box = sizer.current;
    const element = host.current;
    if (!view || !box || !element) return;
    let cancelled = false;
    // The pages' own width, once they render
    let pageWidth = 0;
    // Writes styles, not state, so a resize renders nothing
    const observer = new ResizeObserver(() => {
      if (!pageWidth) return;
      const { paddingLeft, paddingRight } = getComputedStyle(view);
      const available =
        view.clientWidth - parseFloat(paddingLeft) - parseFloat(paddingRight);
      if (available <= 0) return;
      const scale = available / pageWidth;
      element.style.transform = `scale(${scale})`;
      box.style.width = `${pageWidth * scale}px`;
      box.style.height = `${element.offsetHeight * scale}px`;
    });
    observer.observe(view);
    // The pages grow as their images load
    observer.observe(element);
    const root = element.shadowRoot ?? element.attachShadow({ mode: "open" });
    void renderDocx(bytes.buffer)
      .then(({ body, styles }) => {
        if (cancelled) return;
        root.replaceChildren(styles, body);
        pageWidth = Math.max(
          0,
          ...Array.from(
            body.querySelectorAll<HTMLElement>("section.docx"),
            (page) => page.offsetWidth
          )
        );
        // The new width is a resize, which scales the pages
        if (pageWidth) element.style.width = `${pageWidth}px`;
        // From the paragraphs' text, which needs no layout, so a preview that
        // renders in a hidden tab still counts and copies its words
        setText(
          Array.from(
            body.querySelectorAll("p"),
            (paragraph) => paragraph.textContent
          ).join("\n")
        );
      })
      .catch(() => {
        if (!cancelled) onError();
      });
    return () => {
      cancelled = true;
      observer.disconnect();
    };
  }, [bytes, onError]);

  return (
    <>
      <div
        ref={scroller}
        // A stable gutter keeps the width from changing with the scrollbar,
        // which would scale the pages again
        className="relative h-full overflow-auto bg-background-neutral-02 px-2 pt-2 pb-16 [scrollbar-gutter:stable]"
      >
        {text === null && (
          <Section className="absolute inset-0">
            <OnyxLoader size={32} />
          </Section>
        )}
        <div ref={sizer} className="relative mx-auto">
          <div ref={host} className="absolute top-0 left-0 origin-top-left" />
        </div>
      </div>
      <FloatingFooter
        left={
          text !== null && (
            <Text as="p" font="main-ui-body" color="text-03">
              {t("wordCount.label", {
                count: text.split(/\s+/).filter(Boolean).length,
              })}
            </Text>
          )
        }
        right={text === null ? download : textActions(text)}
      />
    </>
  );
}
