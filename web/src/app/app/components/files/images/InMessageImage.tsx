import { memo, useState } from "react";
import { SvgDownload } from "@opal/icons";
import { ImageShape } from "@/app/app/services/streamingModels";
import { FullImageModal } from "@/app/app/components/files/images/FullImageModal";
import { buildImgUrl } from "@/app/app/components/files/images/utils";
import { Button } from "@opal/components";
import { Hoverable } from "@opal/core";
import { cn } from "@/lib/utils";

const DEFAULT_SHAPE: ImageShape = "square";

const SHAPE_CLASSES: Record<ImageShape, { container: string; image: string }> =
  {
    square: {
      container: "max-w-96 max-h-96",
      image: "max-w-96 max-h-96",
    },
    landscape: {
      container: "max-w-[28rem] max-h-72",
      image: "max-w-[28rem] max-h-72",
    },
    portrait: {
      container: "max-w-72 max-h-[28rem]",
      image: "max-w-72 max-h-[28rem]",
    },
  };

// Used to stop image flashing as images are loaded and response continues
const loadedImages = new Set<string>();

interface InMessageImageProps {
  fileId: string;
  fileName?: string;
  shape?: ImageShape;
}

export const InMessageImage = memo(function InMessageImage({
  fileId,
  fileName,
  shape = DEFAULT_SHAPE,
}: InMessageImageProps) {
  const [fullImageShowing, setFullImageShowing] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(loadedImages.has(fileId));

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

  return (
    <>
      <FullImageModal
        fileId={fileId}
        open={fullImageShowing}
        onOpenChange={(open) => setFullImageShowing(open)}
      />

      <Hoverable.Root group="messageImage" widthVariant="fit">
        <div className={cn("relative", shapeContainerClasses)}>
          {!imageLoaded && (
            <div className="absolute inset-0 bg-background-tint-02 animate-pulse rounded-lg" />
          )}

          <img
            width={1200}
            height={1200}
            alt="Chat Message Image"
            onLoad={() => {
              loadedImages.add(fileId);
              setImageLoaded(true);
            }}
            className={cn(
              "object-contain object-left overflow-hidden rounded-lg w-full h-full transition-opacity duration-300 cursor-pointer",
              shapeImageClasses,
              imageLoaded ? "opacity-100" : "opacity-0"
            )}
            onClick={() => setFullImageShowing(true)}
            src={buildImgUrl(fileId)}
            loading="lazy"
          />

          {/* Download button - appears on hover */}
          <div className="absolute bottom-2 right-2 z-10">
            <Hoverable.Item group="messageImage" variant="opacity-on-hover">
              <Button
                icon={SvgDownload}
                tooltip="Download"
                onClick={handleDownload}
              />
            </Hoverable.Item>
          </div>
        </div>
      </Hoverable.Root>
    </>
  );
});
