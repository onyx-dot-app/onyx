"use client";

import { useState } from "react";
import { FullImageModal } from "./FullImageModal";
import { buildImgUrl } from "./utils";

export function InMessageImage({ fileId }: { fileId: string }) {
  const [fullImageShowing, setFullImageShowing] = useState(false);

  return (
    <>
      <FullImageModal
        fileId={fileId}
        open={fullImageShowing}
        onOpenChange={(open) => setFullImageShowing(open)}
      />

      <img
        className="object-cover object-center overflow-hidden rounded-lg w-full h-full max-w-64 max-h-64 transition-opacity duration-300 opacity-100"
        onClick={() => setFullImageShowing(true)}
        src={buildImgUrl(fileId)}
        loading="lazy"
      />
    </>
  );
}
