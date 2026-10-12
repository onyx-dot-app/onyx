"use client";

import { useState, useRef, type ReactNode, type Ref } from "react";
import { useInView } from "motion/react";
import { useTranslations } from "next-intl";
import { Button, SelectCard, Text } from "@opal/components";
import { Hoverable } from "@opal/core";
import { SvgDownloadCloud, SvgFolder } from "@opal/icons";
import { MarkdownContent } from "@/app/craft/components/output-panel/MarkdownFilePreview";
import { getFileIcon } from "@/lib/utils";
import { useFilePreview } from "@/lib/build/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  downloadArtifactFile,
  fetchFileContent,
  fetchOutputThumbnail,
} from "@/app/craft/services/apiServices";
import type { OutputFile } from "@/app/craft/types/streamingTypes";

interface OutputTileProps {
  sessionId: string;
  file: OutputFile;
  isActive: boolean;
  showPath?: boolean;
  onFileOpen: (path: string, fileName: string) => void;
}

export function OutputTile({
  sessionId,
  file,
  isActive,
  onFileOpen,
  showPath = false,
}: OutputTileProps) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { margin: "200px" });
  const image = /\.(png|jpe?g|gif|webp|svg|avif)$/i.test(file.path);
  const text =
    /\.(txt|md|csv|json|html?|css|js|ts|tsx|jsx|py|yaml|yml|xml|sql|sh|log)$/i.test(
      file.path
    );
  const document = /\.(pdf|pptx?)$/i.test(file.path);
  const canPreview =
    (image && file.size <= 2 * 1024 * 1024) ||
    (text && file.size <= 256 * 1024) ||
    (document && file.size <= 20 * 1024 * 1024);
  const { data, error } = useFilePreview(
    SWR_KEYS.buildSessionOutputThumbnail(sessionId, file.path),
    () =>
      document
        ? fetchOutputThumbnail(sessionId, file.path).then((content) => ({
            content,
            mimeType: "image/jpeg",
            isImage: true,
          }))
        : fetchFileContent(sessionId, file.path),
    { revision: file.revision, isActive: isActive && inView && canPreview }
  );
  const name = file.path.split("/").at(-1) ?? file.path;
  const FileIcon = getFileIcon(name);
  const preview = data && !data.error && canPreview ? data : undefined;

  return (
    <OutputTileFrame
      ref={ref}
      label={file.path}
      name={showPath ? file.path.replace(/^outputs\//, "") : name}
      onOpen={() => onFileOpen(file.path, name)}
      onDownload={() => downloadArtifactFile(sessionId, file.path)}
      preview={
        <>
          {preview?.isImage ? (
            <OutputImageThumbnail
              key={preview.content}
              src={preview.content}
              fallback={
                <FileIcon
                  size={32}
                  className="size-8 stroke-text-03 @[40rem]:size-10"
                />
              }
            />
          ) : preview?.content ? (
            <div
              className="relative h-full w-full overflow-hidden bg-background-neutral-00 text-start pointer-events-none"
              inert
            >
              <div className="absolute start-0 top-0 w-[222%] origin-top-left scale-45 p-5 rtl:origin-top-right">
                {/\.md$/i.test(file.path) ? (
                  <MarkdownContent
                    content={preview.content.slice(0, 4000)}
                    thumbnail
                  />
                ) : (
                  <div className="whitespace-pre-wrap">
                    <Text
                      font="secondary-mono"
                      color="text-04"
                      as="p"
                      wordWrap="wrap-anywhere"
                    >
                      {preview.content.slice(0, 4000)}
                    </Text>
                  </div>
                )}
              </div>
            </div>
          ) : canPreview && !data && !error ? (
            <div className="h-full w-full bg-background-neutral-02" />
          ) : (
            <FileIcon
              size={32}
              className="size-8 stroke-text-03 @[40rem]:size-10"
            />
          )}
        </>
      }
    />
  );
}

function OutputImageThumbnail({
  src,
  fallback,
}: {
  src: string;
  fallback: ReactNode;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) return fallback;
  return (
    // Sandbox images are authenticated data URLs, not public Next.js assets.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt=""
      onError={() => setFailed(true)}
      className="h-full w-full object-contain"
    />
  );
}

export function OutputFolderTile({
  name,
  onOpen,
}: {
  name: string;
  onOpen: () => void;
}) {
  return (
    <SelectCard
      role="button"
      aria-label={name}
      tabIndex={0}
      state="empty"
      padding={3}
      rounding={2}
      onClick={onOpen}
    >
      <div className="flex min-w-0 items-center gap-2">
        <SvgFolder size={20} className="shrink-0 stroke-text-03" aria-hidden />
        <Text
          font="secondary-body"
          color="text-04"
          maxLines={1}
          wordWrap="wrap-anywhere"
        >
          {name}
        </Text>
      </div>
    </SelectCard>
  );
}

interface OutputTileFrameProps {
  ref?: Ref<HTMLDivElement>;
  label: string;
  name: string;
  preview: ReactNode;
  onOpen: () => void;
  onDownload?: () => void;
}

function OutputTileFrame({
  ref,
  label,
  name,
  preview,
  onOpen,
  onDownload,
}: OutputTileFrameProps) {
  const t = useTranslations("craft.filesTab");
  return (
    <div className="relative">
      <Hoverable.Root group="output-tile">
        <SelectCard
          ref={ref}
          role="button"
          tabIndex={0}
          aria-label={label}
          state="filled"
          border="none"
          padding={2}
          rounding={3}
          onClick={onOpen}
        >
          <div className="flex min-w-0 flex-col gap-1.5">
            <div
              className="flex aspect-[3/2] min-h-0 items-center justify-center overflow-hidden rounded-md bg-background-neutral-03"
              aria-hidden
            >
              {preview}
            </div>
            <div className="min-w-0 pe-7">
              <Text
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
