import { useRef, useState } from "react";
import { FileDescriptor } from "@/app/chat/interfaces";
import { FiLoader, FiFileText } from "react-icons/fi";
import { InputBarPreviewImage } from "./images/InputBarPreviewImage";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgX from "@/icons/x";

export interface InputBarPreviewImageProviderProps {
  file: FileDescriptor;
  onDelete: () => void;
  isUploading: boolean;
}

export function InputBarPreviewImageProvider({
  file,
  onDelete,
  isUploading,
}: InputBarPreviewImageProviderProps) {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <div
      className="h-6 relative"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {isHovered && <IconButton icon={SvgX} onClick={onDelete} internal />}
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

export interface InputBarPreviewProps {
  file: FileDescriptor;
  onDelete: () => void;
  isUploading: boolean;
}

export function InputBarPreview({
  file,
  onDelete,
  isUploading,
}: InputBarPreviewProps) {
  const fileNameRef = useRef<HTMLDivElement>(null);

  return (
    <div className="relative">
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
          <FiLoader size={12} className="animate-spin text-white" />
        </div>
      )}
      <div
        className={`
        flex
        items-center
        px-2
        bg-accent-background-hovered
        border
        gap-x-1.5
        border-border
        rounded-md
        box-border
        h-8
      `}
      >
        <div className="flex-shrink-0">
          <div
            className="
            w-5
            h-5
            bg-document
            flex
            items-center
            justify-center
            rounded-md
          "
          >
            <FiFileText size={12} className="text-white" />
          </div>
        </div>

        <SimpleTooltip tooltip={file.name ?? undefined}>
          <div
            ref={fileNameRef}
            className={`font-medium text-sm line-clamp-1 break-all ellipses max-w-48`}
          >
            {file.name}
          </div>
        </SimpleTooltip>

        <IconButton onClick={onDelete} icon={SvgX} internal />
      </div>
    </div>
  );
}
