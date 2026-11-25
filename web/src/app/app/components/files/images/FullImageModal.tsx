"use client";

import { useEffect } from "react";
import { cn } from "@opal/utils";
import * as Dialog from "@radix-ui/react-dialog";
import { useTranslations } from "next-intl";

interface FullImageModalProps {
  src: string;
  alt?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCloseAutoFocus?: (event: Event) => void;
}

export function FullImageModal({
  src,
  alt,
  open,
  onOpenChange,
  onCloseAutoFocus,
}: FullImageModalProps) {
  const t = useTranslations("chat.files");

  // pre-fetch image
  useEffect(() => {
    const img = new Image();
    img.src = src;
  }, [src]);

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black bg-opacity-80 z-modal-overlay backdrop-blur-xl" />
        <Dialog.Content
          onCloseAutoFocus={onCloseAutoFocus}
          className={cn(
            "fixed inset-0 flex items-center justify-center p-4 z-modal",
            "max-w-(--breakpoint-lg) h-fit top-1/2 left-1/2 -translate-y-2/4 -translate-x-2/4",
            "focus:outline-hidden"
          )}
        >
          <Dialog.Title className="sr-only">
            {t("inMessageImage.viewFullImage.label")}
          </Dialog.Title>
          <img
            src={src}
            alt={alt || t("fullImageModal.image.alt")}
            className="max-w-full max-h-[calc(100dvh-2rem)] object-contain"
          />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
