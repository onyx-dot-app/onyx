import { memo, useState } from "react";
import {
  SvgCheck,
  SvgDownload,
  SvgFolderPlus,
  SvgSimpleLoader,
} from "@opal/icons";
import { ImageShape } from "@/app/app/services/streamingModels";
import { FullImageModal } from "@/app/app/components/files/images/FullImageModal";
import { buildImgUrl } from "@/app/app/components/files/images/utils";
import { useProjectsContext } from "@/lib/projects/providers";
import { Button } from "@opal/components";
import { Hoverable } from "@opal/core";
import { toast } from "@opal/layouts";
import { cn, clickOnKeyDown } from "@opal/utils";
import { useTranslations } from "next-intl";

const DEFAULT_SHAPE: ImageShape = "square";

const SHAPE_CLASSES: Record<ImageShape, { container: string; image: string }> =
  {
    square: {
      container: "max-w-96 max-h-96",
      image: "max-w-96 max-h-96",
    },
    landscape: {
      container: "max-w-112 max-h-72",
      image: "max-w-112 max-h-72",
    },
    portrait: {
      container: "max-w-72 max-h-112",
      image: "max-w-72 max-h-112",
    },
  };

// Used to stop image flashing as images are loaded and response continues
const loadedImages = new Set<string>();

interface InMessageImageProps {
  fileId: string;
  fileName?: string;
  shape?: ImageShape;
  canIndex?: boolean;
}

export const InMessageImage = memo(function InMessageImage({
  fileId,
  fileName,
  shape = DEFAULT_SHAPE,
  canIndex = false,
}: InMessageImageProps) {
  const t = useTranslations("chat.files");
  const { indexFile } = useProjectsContext();
  const [fullImageShowing, setFullImageShowing] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(loadedImages.has(fileId));
  const [isIndexing, setIsIndexing] = useState(false);
  const [isIndexed, setIsIndexed] = useState(false);

  const normalizedShape = SHAPE_CLASSES[shape] ? shape : DEFAULT_SHAPE;
  const { container: shapeContainerClasses, image: shapeImageClasses } =
    SHAPE_CLASSES[normalizedShape];

  const handleDownload = async (e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent opening the full image modal

    try {
      const response = await fetch(buildImgUrl(fileId));
      if (!response.ok) {
        console.error("Failed to download image:", response.status);
        return;
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = fileName || `image-${fileId}.png`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (error) {
      console.error("Failed to download image:", error);
    }
  };

  const handleIndex = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isIndexing || isIndexed) {
      return;
    }

    setIsIndexing(true);
    try {
      await indexFile(fileId, fileName);
      setIsIndexed(true);
      toast.success(t("inMessageImage.indexButton.success.toast"));
    } catch (error) {
      console.error("Failed to index image:", error);
      toast.error(t("inMessageImage.indexButton.error.toast"));
    } finally {
      setIsIndexing(false);
    }
  };

  return (
    <>
      <FullImageModal
        fileId={fileId}
        open={fullImageShowing}
        onOpenChange={(open) => setFullImageShowing(open)}
      />

      <Hoverable.Root group="messageImage" width="fit">
        {/* The container holds its own download button, so it takes the button
            semantics rather than a <button> wrapping a <button>. */}
        <div
          className={cn("relative", shapeContainerClasses)}
          role="button"
          tabIndex={0}
          aria-label={t("inMessageImage.viewFullImage.label")}
          onClick={() => setFullImageShowing(true)}
          onKeyDown={clickOnKeyDown(() => setFullImageShowing(true))}
        >
          {!imageLoaded && (
            <div className="absolute inset-0 bg-background-tint-02 animate-pulse rounded-lg" />
          )}

          <img
            width={1200}
            height={1200}
            alt={t("inMessageImage.image.alt")}
            onLoad={() => {
              loadedImages.add(fileId);
              setImageLoaded(true);
            }}
            className={cn(
              "object-contain object-left rtl:object-right overflow-hidden rounded-lg w-full h-full transition-opacity duration-300 cursor-pointer",
              shapeImageClasses,
              imageLoaded ? "opacity-100" : "opacity-0"
            )}
            src={buildImgUrl(fileId)}
            loading="lazy"
          />

          <div className="absolute bottom-2 end-2 z-10 flex gap-1">
            {canIndex && (
              <Hoverable.Item group="messageImage" variant="appear-on-hover">
                <Button
                  icon={
                    isIndexing
                      ? SvgSimpleLoader
                      : isIndexed
                        ? SvgCheck
                        : SvgFolderPlus
                  }
                  tooltip={
                    isIndexed
                      ? t("inMessageImage.indexButton.doneTooltip")
                      : t("inMessageImage.indexButton.tooltip")
                  }
                  disabled={isIndexing}
                  onClick={handleIndex}
                />
              </Hoverable.Item>
            )}
            <Hoverable.Item group="messageImage" variant="appear-on-hover">
              <Button
                icon={SvgDownload}
                tooltip={t("inMessageImage.downloadButton.tooltip")}
                onClick={handleDownload}
              />
            </Hoverable.Item>
          </div>
        </div>
      </Hoverable.Root>
    </>
  );
});
