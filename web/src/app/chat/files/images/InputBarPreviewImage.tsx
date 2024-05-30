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
      <div>
        <img
          onClick={() => setFullImageShowing(true)}
          className="h-16 w-16 object-cover rounded-lg bg-background cursor-pointer"
          src={buildImgUrl(fileId)}
        />
      </div>
    </>
  );
}
