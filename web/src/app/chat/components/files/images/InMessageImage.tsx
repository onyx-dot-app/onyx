import { useState } from "react";
import { FiDownload } from "react-icons/fi";
import { ImageShape } from "@/app/chat/services/streamingModels";
import { FullImageModal } from "@/app/chat/components/files/images/FullImageModal";
import { buildImgUrl } from "@/app/chat/components/files/images/utils";
import IconButton from "@/refresh-components/buttons/IconButton";
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

interface InMessageImageProps {
  fileId: string;
  shape?: ImageShape;
}

export function InMessageImage({
  fileId,
  shape = DEFAULT_SHAPE,
}: InMessageImageProps) {
  const [fullImageShowing, setFullImageShowing] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);

  const normalizedShape = SHAPE_CLASSES[shape] ? shape : DEFAULT_SHAPE;
  const { container: shapeContainerClasses, image: shapeImageClasses } =
    SHAPE_CLASSES[normalizedShape];

  const handleDownload = async (e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent opening the full image modal

    try {
      const response = await fetch(buildImgUrl(fileId));
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `image-${fileId}.png`; // You can adjust the filename/extension as needed
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

      <div
        className={cn("relative w-full h-full group", shapeContainerClasses)}
      >
        {!imageLoaded && (
          <div className="absolute inset-0 bg-background-tint-02 animate-pulse rounded-lg" />
        )}

        <img
          width={1200}
          height={1200}
          alt="Chat Message Image"
          onLoad={() => setImageLoaded(true)}
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
        <div
          className={cn(
            "absolute bottom-2 right-2 opacity-0 group-hover:opacity-100 z-10"
          )}
        >
          <IconButton
            icon={FiDownload}
            tooltip="Download"
            onClick={handleDownload}
          />
        </div>
      </div>
    </>
  );
}
