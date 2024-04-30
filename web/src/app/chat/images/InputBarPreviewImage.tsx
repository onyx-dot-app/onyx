"use client";

import { useState } from "react";
import { FiX } from "react-icons/fi";
import { buildImgUrl } from "./utils";
import { FullImageModal } from "./FullImageModal";

export function InputBarPreviewImage({
  fileId,
  onDelete,
}: {
  fileId: string;
  onDelete: () => void;
}) {
  const [isHovered, setIsHovered] = useState(false);
  const [fullImageShowing, setFullImageShowing] = useState(false);

  return (
    <>
      <FullImageModal
        fileId={fileId}
        open={fullImageShowing}
        onOpenChange={(open) => setFullImageShowing(open)}
      />
      <div
        className="p-1 relative"
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        {isHovered && (
          <button
            onClick={onDelete}
            className="absolute top-0 right-0 cursor-pointer border-none bg-hover p-1 rounded-full"
          >
            <FiX />
          </button>
        )}
        <img
          onClick={() => setFullImageShowing(true)}
          className="h-16 w-16 object-cover rounded-lg bg-background cursor-pointer"
          src={buildImgUrl(fileId)}
        />
      </div>
    </>
  );
}
