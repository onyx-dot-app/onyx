"use client";

import React from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import {
  SvgDownloadCloud,
  SvgLoader,
  SvgArrowLeft,
  SvgArrowRight,
  SvgExternalLink,
  SvgRevert,
} from "@opal/icons";
import { IconProps } from "@opal/types";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";

/** SvgLoader wrapped with animate-spin so it can be passed as a Button leftIcon */
const SpinningLoader: React.FunctionComponent<IconProps> = (props) => (
  <SvgLoader {...props} className={cn(props.className, "animate-spin")} />
);

export interface UrlBarProps {
  displayUrl: string;
  showNavigation?: boolean;
  canGoBack?: boolean;
  canGoForward?: boolean;
  onBack?: () => void;
  onForward?: () => void;
  previewUrl?: string | null;
  /** Optional callback to download the raw file — shows a cloud-download icon inside the URL pill */
  onDownloadRaw?: () => void;
  /** Tooltip text for the raw download button */
  downloadRawTooltip?: string;
  /** Optional download callback — shows an export button in the URL bar when provided */
  onDownload?: () => void;
  /** Whether a download/export is currently in progress */
  isDownloading?: boolean;
  /** Optional refresh callback — shows a refresh icon at the right edge of the URL pill */
  onRefresh?: () => void;
}

/**
 * UrlBar - Chrome-style URL/status bar below tabs
 * Shows the current URL/path based on active tab or file preview
 * Optionally shows back/forward navigation buttons
 * For Preview tab, shows a button to open the URL in a new browser tab
 * For downloadable files, shows a download icon
 */
export default function UrlBar({
  displayUrl,
  showNavigation = false,
  canGoBack = false,
  canGoForward = false,
  onBack,
  onForward,
  previewUrl,
  onDownloadRaw,
  downloadRawTooltip = "Download file",
  onDownload,
  isDownloading = false,
  onRefresh,
}: UrlBarProps) {
  const handleOpenInNewTab = () => {
    if (previewUrl) {
      window.open(previewUrl, "_blank", "noopener,noreferrer");
    }
  };

  return (
    <div className="px-3 pb-2">
      <div className="flex items-center gap-1">
        {/* Navigation buttons + refresh */}
        {showNavigation && (
          <div className="flex items-center gap-0.5">
            <button
              onClick={onBack}
              disabled={!canGoBack}
              className={cn(
                "p-1.5 rounded-full transition-colors",
                canGoBack
                  ? "hover:bg-background-tint-03 text-text-03"
                  : "text-text-02 cursor-not-allowed"
              )}
              aria-label="Go back"
            >
              <SvgArrowLeft size={16} />
            </button>
            <button
              onClick={onForward}
              disabled={!canGoForward}
              className={cn(
                "p-1.5 rounded-full transition-colors",
                canGoForward
                  ? "hover:bg-background-tint-03 text-text-03"
                  : "text-text-02 cursor-not-allowed"
              )}
              aria-label="Go forward"
            >
              <SvgArrowRight size={16} />
            </button>
            {onRefresh && (
              <button
                onClick={onRefresh}
                className="p-1.5 rounded-full transition-colors hover:bg-background-tint-03 text-text-03"
                aria-label="Refresh"
              >
                <SvgRevert size={14} className="-scale-x-100" />
              </button>
            )}
          </div>
        )}
        {/* URL display */}
        <div className="flex-1 flex items-center px-3 py-1.5 bg-background-tint-02 rounded-full gap-2 min-h-[2.25rem]">
          {/* Download raw file button */}
          {onDownloadRaw && (
            <SimpleTooltip tooltip={downloadRawTooltip} delayDuration={200}>
              <button
                onClick={onDownloadRaw}
                className="flex-shrink-0 p-0.5 rounded transition-colors hover:bg-background-tint-03 text-text-03"
                aria-label={downloadRawTooltip}
              >
                <SvgDownloadCloud size={14} />
              </button>
            </SimpleTooltip>
          )}
          {/* Open in new tab button - only shown for Preview tab with valid URL */}
          {previewUrl && (
            <SimpleTooltip tooltip="open in a new tab" delayDuration={200}>
              <button
                onClick={handleOpenInNewTab}
                className="flex-shrink-0 p-0.5 rounded transition-colors hover:bg-background-tint-03 text-text-03"
                aria-label="open in a new tab"
              >
                <SvgExternalLink size={14} />
              </button>
            </SimpleTooltip>
          )}
          <Text secondaryBody text03 className="truncate">
            {displayUrl}
          </Text>
        </div>
        {/* Export button — shown for downloadable file previews (e.g. markdown → docx) */}
        {onDownload && (
          <Button
            action
            tertiary
            leftIcon={isDownloading ? SpinningLoader : SvgExternalLink}
            disabled={isDownloading}
            onClick={onDownload}
          >
            {isDownloading ? "Exporting..." : "Export to .docx"}
          </Button>
        )}
      </div>
    </div>
  );
}
