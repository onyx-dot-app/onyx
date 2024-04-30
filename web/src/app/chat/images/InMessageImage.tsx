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
        className={`
          max-w-lg 
          rounded-lg 
          bg-transparent 
          cursor-pointer 
          transition-opacity 
          duration-300 
          opacity-100`}
        onClick={() => setFullImageShowing(true)}
        src={buildImgUrl(fileId)}
        loading="lazy"
      />
    </>
  );
}
