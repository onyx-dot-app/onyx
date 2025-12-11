"use client";

import React from "react";
import { IconProps } from "@/icons";
import { cn, noProp } from "@/lib/utils";
import SvgImage from "@/icons/image";
import SvgPlus from "@/icons/plus";
import SvgUploadCloud from "@/icons/upload-cloud";
import SvgX from "@/icons/x";
import SvgRefreshCw from "@/icons/refresh-cw";
import IconButton from "@/refresh-components/buttons/IconButton";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import Text from "@/refresh-components/texts/Text";

export interface InputImageProps {
  // Content variants
  content?: "icon" | "placeholder" | "upload" | "image";

  // State control
  disabled?: boolean;

  // Image source (for "image" content)
  src?: string;
  alt?: string;

  // Icon (for "icon" content)
  icon?: React.FunctionComponent<IconProps>;

  // Callbacks
  onEdit?: () => void;
  onRemove?: () => void;
  onRevert?: () => void;

  // Control visibility of action buttons
  showRemove?: boolean;
  showRevert?: boolean;

  // Size control
  size?: number;

  className?: string;
}

export default function InputImage({
  content = "icon",
  disabled = false,
  src,
  alt = "Image",
  icon: Icon = SvgImage,
  onEdit,
  onRemove,
  onRevert,
  showRemove = true,
  showRevert = false,
  size = 120,
  className,
}: InputImageProps) {
  const isInteractive = !disabled && onEdit;

  // Render content based on variant
  const renderContent = () => {
    switch (content) {
      case "placeholder":
        return <SvgPlus className="w-6 h-6 stroke-text-02" />;

      case "upload":
        return (
          <>
            {/* Mosaic background pattern for upload state */}
            <div
              className="absolute inset-0 opacity-50 pointer-events-none"
              style={{
                backgroundImage: `url("data:image/svg+xml,%3Csvg width='36' height='36' viewBox='0 0 36 36' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='%239C92AC' fill-opacity='0.4'%3E%3Ccircle cx='18' cy='18' r='18'/%3E%3C/g%3E%3C/svg%3E")`,
                backgroundSize: "36px 36px",
                backgroundPosition: "0 0",
                backgroundRepeat: "repeat",
              }}
            />
            <div className="flex items-center justify-center p-[2px] w-7 h-7 relative z-10">
              <SvgUploadCloud className="w-6 h-6 stroke-text-03" />
            </div>
          </>
        );

      case "image":
        return src ? (
          <img
            src={src}
            alt={alt}
            className="absolute inset-0 w-full h-full object-cover"
          />
        ) : (
          <div className="flex items-center justify-center p-2">
            <Icon className="w-8 h-8 stroke-text-03" />
          </div>
        );

      case "icon":
      default:
        return (
          <div className="flex items-center justify-center p-[2px] w-9 h-9">
            <Icon className="w-8 h-8 stroke-text-03" />
          </div>
        );
    }
  };

  return (
    <div
      className={cn("relative group", className)}
      style={{ width: size, height: size }}
    >
      {/* Main container */}
      <button
        type="button"
        onClick={disabled ? undefined : onEdit}
        disabled={disabled}
        className={cn(
          "relative w-full h-full rounded-full overflow-hidden",
          "border bg-background-neutral-00",
          "flex items-center justify-center",
          "transition-all duration-150",
          // Default state
          content === "image" && src ? "border-solid" : "border-dashed",
          "border-border-01",
          // Hover state
          isInteractive && [
            "group-hover:border-solid group-hover:border-border-03",
          ],
          // Focus state
          isInteractive && [
            "focus-visible:outline-none focus-visible:border-solid focus-visible:border-border-05",
            "focus-visible:ring-2 focus-visible:ring-background-tint-04 focus-visible:ring-offset-0",
          ],
          // Active/Pressed state
          isInteractive && ["active:border-border-03"],
          // Disabled state
          disabled && ["opacity-50 cursor-not-allowed border-dashed"]
        )}
        aria-label={onEdit ? "Edit image" : undefined}
      >
        {renderContent()}

        {/* Edit container - shows on hover/focus */}
        {isInteractive && (
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

            {/* Revert button */}
            {showRevert && onRevert && (
              <div className="ml-1 pointer-events-auto">
                <SimpleTooltip tooltip="Restore Default" side="top">
                  <IconButton
                    icon={SvgRefreshCw}
                    onClick={noProp(onRevert)}
                    type="button"
                    internal
                    aria-label="Restore default"
                  />
                </SimpleTooltip>
              </div>
            )}
          </div>
        )}
      </button>

      {/* Remove button - top left corner */}
      {isInteractive && showRemove && onRemove && (
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
