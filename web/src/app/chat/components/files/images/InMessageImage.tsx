import { useState } from "react";
import { FullImageModal } from "./FullImageModal";
import { buildImgUrl } from "./utils";

export function InMessageImage({ fileId }: { fileId: string }) {
  const [fullImageShowing, setFullImageShowing] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);

  return (
    <>
      <FullImageModal
        fileId={fileId}
        open={fullImageShowing}
        onOpenChange={(open) => setFullImageShowing(open)}
      />

      <div className="relative w-full h-full max-w-96 max-h-96">
        {!imageLoaded && (
          <div className="absolute inset-0 bg-background-200 animate-pulse rounded-lg" />
        )}

        <img
          width={1200}
          height={1200}
          alt="Chat Message Image"
          onLoad={() => setImageLoaded(true)}
          className={`object-contain object-left overflow-hidden rounded-lg w-full h-full max-w-96 max-h-96 transition-opacity duration-300
             ${imageLoaded ? "opacity-100" : "opacity-0"}`}
          onClick={() => setFullImageShowing(true)}
          src={buildImgUrl(fileId)}
          loading="lazy"
        />
      </div>
    </>
  );
}
