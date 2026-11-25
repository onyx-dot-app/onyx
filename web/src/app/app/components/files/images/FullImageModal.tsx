"use client";

// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).
import { useEffect, useState } from "react";
import { cn } from "@opal/utils";
import * as Dialog from "@radix-ui/react-dialog";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import type { GalleryImage } from "@/app/app/components/files/images/gallery";
import { SvgChevronLeft, SvgChevronRight } from "@opal/icons";

interface FullImageModalProps {
  images: GalleryImage[];
  initialIndex?: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCloseAutoFocus?: (event: Event) => void;
}

export function FullImageModal({
  images,
  initialIndex = 0,
  open,
  onOpenChange,
  onCloseAutoFocus,
}: FullImageModalProps) {
  const t = useTranslations("chat.files");
  const [offset, setOffset] = useState(0);
  const count = images.length;
  const index =
    count > 0 ? (((initialIndex + offset) % count) + count) % count : 0;
  const current = images[index];

  useEffect(() => {
    for (const { url } of images) {
      const img = new Image();
      img.src = url;
    }
  }, [images]);

  if (!current) return null;

  const step = (direction: -1 | 1) =>
    setOffset((current) => current + direction);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (count <= 1) return;
    const rtl = document.documentElement.dir === "rtl";
    if (event.key === "ArrowLeft") step(rtl ? 1 : -1);
    else if (event.key === "ArrowRight") step(rtl ? -1 : 1);
    else return;
    event.preventDefault();
    event.stopPropagation();
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black bg-opacity-80 z-modal-overlay backdrop-blur-xl" />
        <Dialog.Content
          onCloseAutoFocus={onCloseAutoFocus}
          onKeyDown={onKeyDown}
          className={cn(
            "fixed inset-0 flex items-center justify-center p-4 z-modal",
            "w-full max-w-(--breakpoint-lg) h-fit top-1/2 right-auto left-1/2 -translate-y-2/4 -translate-x-2/4",
            "focus:outline-hidden"
          )}
        >
          <Dialog.Title className="sr-only">
            {t("inMessageImage.viewFullImage.label")}
          </Dialog.Title>
          <img
            src={current.url}
            alt={current.alt || t("fullImageModal.image.alt")}
            className="max-w-full max-h-[calc(100dvh-2rem)] object-contain"
          />
          {count > 1 && (
            <>
              <div className="absolute start-2 top-1/2 -translate-y-1/2">
                <Button
                  icon={SvgChevronLeft}
                  prominence="secondary"
                  tooltip={t("fullImageModal.previous")}
                  aria-label={t("fullImageModal.previous")}
                  onClick={() => step(-1)}
                />
              </div>
              <div className="absolute end-2 top-1/2 -translate-y-1/2">
                <Button
                  icon={SvgChevronRight}
                  prominence="secondary"
                  tooltip={t("fullImageModal.next")}
                  aria-label={t("fullImageModal.next")}
                  onClick={() => step(1)}
                />
              </div>
              <div
                className="absolute bottom-2 start-1/2 -translate-x-1/2"
                aria-live="polite"
                aria-atomic="true"
              >
                <Text as="p" font="secondary-body" color="text-light-05">
                  {t("fullImageModal.position", {
                    current: index + 1,
                    total: count,
                  })}
                </Text>
              </div>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
