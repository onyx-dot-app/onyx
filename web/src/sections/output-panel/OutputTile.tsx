"use client";

import { useState, type ReactNode, type Ref } from "react";
import { useTranslations } from "next-intl";
import { Button, SelectCard, Text } from "@opal/components";
import type { RichStr } from "@opal/types";
import { Hoverable } from "@opal/core";
import { SvgDownloadCloud } from "@opal/icons";
import UnseenMarker from "@/app/craft/components/UnseenMarker";

/** An image thumbnail that falls back to an icon when the image fails. */
export function OutputImageThumbnail({
  src,
  fallback,
  lazy = false,
}: {
  src: string;
  fallback: ReactNode;
  // Loads the image only near the viewport
  lazy?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) return fallback;
  return (
    // Sandbox images are authenticated data URLs, not public Next.js assets.
    <img
      src={src}
      alt=""
      loading={lazy ? "lazy" : undefined}
      onError={() => setFailed(true)}
      className="h-full w-full object-contain"
    />
  );
}

interface OutputTileFrameProps {
  ref?: Ref<HTMLDivElement>;
  label: string;
  name: string | RichStr;
  preview: ReactNode;
  onOpen?: () => void;
  onDownload?: () => void;
  isUnseen?: boolean;
}

/** An output tile: a thumbnail, the name under it, and a download on hover. */
export function OutputTileFrame({
  ref,
  label,
  name,
  preview,
  onOpen,
  onDownload,
  isUnseen = false,
}: OutputTileFrameProps) {
  const t = useTranslations("outputPanel.tile");
  return (
    <div className="relative">
      <Hoverable.Root group="output-tile">
        <SelectCard
          ref={ref}
          role={onOpen ? "button" : "group"}
          disabled={!onOpen}
          aria-label={label}
          state="filled"
          border="none"
          padding={2}
          rounding={3}
          onClick={onOpen}
        >
          <div className="relative flex min-w-0 flex-col gap-1.5">
            <div
              className="flex aspect-[3/2] min-h-0 items-center justify-center overflow-hidden rounded-md bg-background-neutral-03"
              aria-hidden={onOpen ? true : undefined}
            >
              {preview}
            </div>
            {isUnseen && (
              <OutputUnseenMarker className="absolute end-2 top-2" />
            )}
            <div className="min-w-0 pe-7">
              {/* Names can come from the model or the sandbox */}
              <Text
                dir="auto"
                font="secondary-body"
                color="text-04"
                maxLines={1}
                as="p"
                wordWrap="wrap-anywhere"
              >
                {name}
              </Text>
            </div>
          </div>
        </SelectCard>
        {onDownload && (
          <div className="absolute end-2 bottom-1">
            <Hoverable.Item group="output-tile" variant="appear-on-hover">
              <Button
                icon={SvgDownloadCloud}
                prominence="tertiary"
                size="xs"
                aria-label={t("download.label")}
                onClick={(event) => {
                  event.stopPropagation();
                  onDownload();
                }}
              />
            </Hoverable.Item>
          </div>
        )}
      </Hoverable.Root>
    </div>
  );
}

/** The marker of an output that the user has not opened. */
export function OutputUnseenMarker({ className }: { className: string }) {
  const t = useTranslations("outputPanel.tile");
  return <UnseenMarker label={t("unseen")} className={className} />;
}

/** The grid that output tiles sit in: two columns, three when wider. */
export function OutputTileGrid({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-2 gap-2 @[24rem]:grid-cols-3">
      {children}
    </div>
  );
}
