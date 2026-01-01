"use client";

import React from "react";
import { cn, noProp } from "@/lib/utils";
import { SvgPlus, SvgX } from "@opal/icons";
import IconButton from "@/refresh-components/buttons/IconButton";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import Text from "@/refresh-components/texts/Text";
import { useImageDropzone } from "@/hooks/useImageDropzone";

type ImageState = "empty" | "withImage" | "dragActive";
type AbledState = "enabled" | "disabled";

const inputImageClasses = {
  container: {
    empty: {
      enabled: [
        "bg-background-neutral-00",
        "hover:bg-background-tint-02",
        "active:bg-background-tint-00",
        "focus-visible:bg-background-tint-01",
        "focus-visible:hover:bg-background-tint-02",
        "border-dashed",
        "hover:border-solid",
        "active:border-solid",
        "border-border-01",
        "hover:border-border-03",
        "active:border-border-05",
        "focus-visible:border-border-05",
      ],
      disabled: [
        "bg-background-neutral-00",
        "border-dashed",
        "border-border-01",
        "opacity-50",
        "cursor-not-allowed",
      ],
    },
    withImage: {
      enabled: [
        "bg-background-neutral-00",
        "hover:bg-background-tint-02",
        "active:bg-background-tint-00",
        "focus-visible:bg-background-tint-01",
        "focus-visible:hover:bg-background-tint-02",
        "border-solid",
        "border-border-01",
        "hover:border-border-03",
        "active:border-border-05",
        "focus-visible:border-border-05",
      ],
      disabled: [
        "bg-background-neutral-00",
        "border-solid",
        "border-border-01",
        "opacity-50",
        "cursor-not-allowed",
      ],
    },
    dragActive: {
      enabled: [
        "bg-background-neutral-00",
        "border-solid",
        "border-2",
        "border-action-link-05",
      ],
      disabled: [
        "bg-background-neutral-00",
        "border-solid",
        "border-2",
        "border-action-link-05",
        "opacity-50",
        "cursor-not-allowed",
      ],
    },
  },
  placeholder: {
    empty: {
      enabled: [
        "stroke-text-02",
        "group-hover:stroke-text-03",
        "group-active:stroke-text-04",
        "group-focus-visible:stroke-text-02",
        "group-focus-visible:group-hover:stroke-text-03",
      ],
      disabled: ["stroke-text-01"],
    },
    withImage: {
      enabled: [],
      disabled: [],
    },
    dragActive: {
      enabled: ["stroke-action-link-05"],
      disabled: ["stroke-action-link-05"],
    },
  },
} as const;

export interface InputImageProps {
  // State control
  disabled?: boolean;

  // Image source
  src?: string;
  alt?: string;

  // Callbacks
  onEdit?: () => void;
  onRemove?: () => void;
  /** Callback when image is dropped onto the component */
  onDrop?: (file: File) => void;
  /** Callback when file is rejected */
  onDropRejected?: (reason: string) => void;

  /** Whether to show the edit overlay on hover (default: true) */
  showEditOverlay?: boolean;

  // Size control
  size?: number;

  className?: string;
}

export default function InputImage({
  disabled = false,
  src,
  alt = "Image",
  onEdit,
  onRemove,
  onDrop,
  onDropRejected,
  showEditOverlay = true,
  size = 120,
  className,
}: InputImageProps) {
  const isInteractive = !disabled && (onEdit || onDrop);
  const hasImage = !!src;

  const { isDragActive, getRootProps, getInputProps, openFilePicker } =
    useImageDropzone({
      onImageAccepted: (file) => {
        onDrop?.(file);
      },
      onImageRejected: (rejections) => {
        const firstRejection = rejections[0];
        const reason = firstRejection?.errors[0]?.message || "File rejected";
        onDropRejected?.(reason);
      },
      disabled: disabled || !onDrop,
    });

  const handleClick = () => {
    if (disabled) return;
    if (onEdit) {
      onEdit();
    } else if (onDrop) {
      openFilePicker();
    }
  };

  // Derive states once
  const imageState: ImageState = isDragActive
    ? "dragActive"
    : hasImage
      ? "withImage"
      : "empty";
  const abled: AbledState = disabled ? "disabled" : "enabled";

  // Single lookup pattern for all classes
  const containerClass = inputImageClasses.container[imageState][abled];
  const placeholderClass = inputImageClasses.placeholder[imageState][abled];

  const dropzoneProps = onDrop ? getRootProps() : {};

  return (
    <div
      className={cn("relative group", className)}
      style={{ width: size, height: size }}
      {...dropzoneProps}
    >
      {/* Hidden input for file selection */}
      {onDrop && <input {...getInputProps()} />}

      {/* Main container */}
      <button
        type="button"
        onClick={handleClick}
        disabled={disabled}
        className={cn(
          "relative w-full h-full rounded-full overflow-hidden",
          "border flex items-center justify-center",
          "transition-all duration-150",
          containerClass
        )}
        aria-label={
          isInteractive ? (hasImage ? "Edit image" : "Upload image") : undefined
        }
      >
        {/* Content */}
        {hasImage ? (
          <img
            src={src}
            alt={alt}
            className="absolute inset-0 w-full h-full object-cover pointer-events-none"
          />
        ) : (
          <SvgPlus
            className={cn("w-6 h-6", placeholderClass, "pointer-events-none")}
          />
        )}

        {/* Drag overlay indicator */}
        {isDragActive && (
          <div className="absolute inset-0 bg-action-link-05/10 flex items-center justify-center rounded-full pointer-events-none">
            <SvgPlus className="w-8 h-8 stroke-action-link-05" />
          </div>
        )}

        {/* Edit overlay - shows on hover/focus when image is uploaded */}
        {showEditOverlay && isInteractive && hasImage && !isDragActive && (
          <div
            className={cn(
              "absolute bottom-0 left-0 right-0",
              "flex items-center justify-center",
              "pb-2.5 pt-1.5",
              "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100",
              "transition-opacity duration-150",
              "backdrop-blur-sm bg-mask-01",
              "pointer-events-none"
            )}
          >
            <div className="pointer-events-auto">
              <SimpleTooltip tooltip="Edit" side="top">
                <div
                  className={cn(
                    "flex items-center justify-center",
                    "px-1 py-0.5 rounded-08"
                  )}
                >
                  <Text
                    className="text-text-03 font-secondary-action"
                    style={{ fontSize: "12px", lineHeight: "16px" }}
                  >
                    Edit
                  </Text>
                </div>
              </SimpleTooltip>
            </div>
          </div>
        )}
      </button>

      {/* Remove button - top left corner (only when image is uploaded) */}
      {isInteractive && hasImage && onRemove && (
        <div
          className={cn(
            "absolute top-1 left-1",
            "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100",
            "transition-opacity duration-150"
          )}
        >
          <IconButton
            icon={SvgX}
            onClick={noProp(onRemove)}
            type="button"
            primary
            className="!w-5 !h-5 !p-0.5 !rounded-04"
            aria-label="Remove image"
          />
        </div>
      )}
    </div>
  );
}
