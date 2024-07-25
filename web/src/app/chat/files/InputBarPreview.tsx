import { useEffect, useRef, useState } from "react";
import { ChatFileType, FileDescriptor } from "../interfaces";

import { FiX, FiLoader, FiFileText } from "react-icons/fi";
import { InputBarPreviewImage } from "./images/InputBarPreviewImage";
import { Tooltip } from "@/components/tooltip/Tooltip";

function DeleteButton({ onDelete }: { onDelete: () => void }) {
  return (
    <button
      onClick={onDelete}
      className="
        absolute
        -top-1
        -right-1
        cursor-pointer
        border-none
        bg-hover
        p-.5
        rounded-full
        z-10
      "
    >
      <FiX />
    </button>
  );
}

export function InputBarPreviewImageProvider({
  file,
  onDelete,
  isUploading,
}: {
  file: FileDescriptor;
  onDelete: () => void;
  isUploading: boolean;
}) {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <div
      className="h-10 relative"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {isHovered && <DeleteButton onDelete={onDelete} />}
      {isUploading && (
        <div
          className="
            absolute
            inset-0
            flex
            items-center
            justify-center
            bg-opacity-50
            rounded-lg
            z-0
          "
        >
          <FiLoader className="animate-spin text-white" />
        </div>
      )}
      <InputBarPreviewImage fileId={file.id} />
    </div>
  );
}

export function InputBarPreview({
  file,
  onDelete,
  isUploading,
}: {
  file: FileDescriptor;
  onDelete: () => void;
  isUploading: boolean;
}) {
  const [isHovered, setIsHovered] = useState(false);

  const fileNameRef = useRef<HTMLDivElement>(null);
  const [isOverflowing, setIsOverflowing] = useState(false);

  useEffect(() => {
    if (fileNameRef.current) {
      setIsOverflowing(
        fileNameRef.current.scrollWidth > fileNameRef.current.clientWidth
      );
    }
  }, [file.name]);

  return (
    <div
      className="relative"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {isUploading && (
        <div
          className="
            absolute
            inset-0
            flex
            items-center
            justify-center
            bg-opacity-50
            rounded-lg
            z-0
          "
        >
          <FiLoader className="animate-spin text-white" />
        </div>
      )}
      <div
        className={`
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
        <div className="flex-shrink-0">
          <div
            className="
            w-6
            h-6
            bg-document
            flex
            items-center
            justify-center
            rounded-md
          "
          >
            <FiFileText className="w-4 h-4 text-white" />
          </div>
        </div>
        <div className="ml-2 relative">
          <Tooltip content={file.name} side="top" align="start">
            <div
              ref={fileNameRef}
              className={`font-medium text-sm line-clamp-1 break-all ellipses max-w-48`}
            >
              {file.name}
            </div>
          </Tooltip>
        </div>
        <button
          onClick={onDelete}
          className="
            cursor-pointer
            border-none
            bg-hover
            p-1
            rounded-full
            z-10
          "
        >
          <FiX />
        </button>
      </div>
    </div>
  );
}
