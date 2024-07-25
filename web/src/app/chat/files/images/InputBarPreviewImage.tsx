"use client";

import { useState } from "react";
import { buildImgUrl } from "./utils";
import { FullImageModal } from "./FullImageModal";

export function InputBarPreviewImage({ fileId }: { fileId: string }) {
  const [fullImageShowing, setFullImageShowing] = useState(false);

  return (
    <>
      <FullImageModal
        fileId={fileId}
        open={fullImageShowing}
        onOpenChange={(open) => setFullImageShowing(open)}
      />
      <div
        className={`
          bg-transparent
          border-none
          flex
          items-center
          p-2
          bg-hover
          border
          border-border
          rounded-md
          box-border
          h-10
      `}
      >
        <img
          onClick={() => setFullImageShowing(true)}
          className="h-8 w-8 object-cover rounded-lg bg-background cursor-pointer"
          src={buildImgUrl(fileId)}
        />
      </div>
    </>
  );
}
