"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { cn, copyText } from "@opal/utils";
import { Text, Button } from "@opal/components";
import {
  SvgDownloadCloud,
  SvgLoader,
  SvgArrowLeft,
  SvgArrowRight,
  SvgExternalLink,
  SvgRevert,
  SvgCheck,
} from "@opal/icons";
import { IconProps } from "@opal/types";
import { Tooltip } from "@opal/components";
import ShareButton from "@/app/craft/components/ShareButton";
import type { SharingScope } from "@/app/craft/types/streamingTypes";

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
  /** Whether the current view is refreshing. */
  isRefreshing?: boolean;
  /** Session ID — when present with previewUrl, shows share button for webapp */
  sessionId?: string;
  /** Sharing scope for the webapp (used when sessionId + previewUrl) */
  sharingScope?: SharingScope;
  /** Callback when sharing scope changes (revalidate webapp info) */
  onScopeChange?: () => void;
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
  downloadRawTooltip,
  onDownload,
  isDownloading = false,
  onRefresh,
  isRefreshing = false,
  sessionId,
  sharingScope = "private",
  onScopeChange,
}: UrlBarProps) {
  const t = useTranslations("craft.urlBar");
  const rawTooltip = downloadRawTooltip ?? t("downloadFile.tooltip");
  const [copiedUrl, setCopiedUrl] = React.useState<string | null>(null);
  const [copyFeedbackKey, setCopyFeedbackKey] = React.useState(0);
  const isDisplayUrlCopyable = React.useMemo(() => {
    try {
      const { protocol } = new URL(displayUrl);
      return protocol === "http:" || protocol === "https:";
    } catch {
      return false;
    }
  }, [displayUrl]);
  const isUrlCopied = copiedUrl === displayUrl;

  React.useEffect(() => {
    setCopiedUrl(null);
  }, [displayUrl]);

  const handleOpenInNewTab = () => {
    if (previewUrl) {
      window.open(previewUrl, "_blank", "noopener,noreferrer");
    }
  };

  const handleCopyUrl = async () => {
    if (!isDisplayUrlCopyable) {
      return;
    }

    try {
      await copyText(displayUrl);
      setCopiedUrl(displayUrl);
      setCopyFeedbackKey((key) => key + 1);
    } catch (err) {
      console.error("Failed to copy URL:", err);
      setCopiedUrl(null);
    }
  };

  const urlText = (
    // dir="ltr": URL structure never reorders, even in an RTL locale.
    <Text as="p" dir="ltr" font="secondary-body" color="text-03" maxLines={1}>
      {displayUrl}
    </Text>
  );

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
              aria-label={t("back.ariaLabel")}
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
              aria-label={t("forward.ariaLabel")}
            >
              <SvgArrowRight size={16} />
            </button>
            {onRefresh && (
              <button
                onClick={onRefresh}
                disabled={isRefreshing}
                className={cn(
                  "p-1.5 rounded-full transition-colors text-text-03",
                  isRefreshing ? "cursor-wait" : "hover:bg-background-tint-03"
                )}
                aria-label={t("refresh.ariaLabel")}
                aria-busy={isRefreshing}
              >
                {isRefreshing ? (
                  <SpinningLoader size={14} />
                ) : (
                  <SvgRevert size={14} className="-scale-x-100" />
                )}
              </button>
            )}
          </div>
        )}
        {/* URL display */}
        <div
          data-testid="url-bar-pill"
          className="flex-1 min-w-0 flex items-center px-3 py-1.5 bg-background-tint-02 rounded-full gap-2 min-h-9"
        >
          {/* Download raw file button */}
          {onDownloadRaw && (
            <Tooltip tooltip={rawTooltip} delayDuration={200}>
              <button
                onClick={onDownloadRaw}
                className="shrink-0 p-0.5 rounded-sm transition-colors hover:bg-background-tint-03 text-text-03"
                aria-label={rawTooltip}
              >
                <SvgDownloadCloud size={14} />
              </button>
            </Tooltip>
          )}
          {/* Open in new tab button - only shown for Preview tab with valid URL */}
          {previewUrl && (
            <Tooltip tooltip={t("openInNewTab.tooltip")} delayDuration={200}>
              <button
                onClick={handleOpenInNewTab}
                className="shrink-0 p-0.5 rounded-sm transition-colors hover:bg-background-tint-03 text-text-03"
                aria-label={t("openInNewTab.tooltip")}
                data-copy-state={isUrlCopied ? "copied" : "idle"}
              >
                {isUrlCopied ? (
                  <SvgCheck
                    key={`copied-${copyFeedbackKey}`}
                    size={14}
                    className="animate-in fade-in-0 zoom-in-95 duration-500 stroke-status-success-05"
                    onAnimationEnd={() => {
                      setCopiedUrl((currentCopiedUrl) =>
                        currentCopiedUrl === displayUrl
                          ? null
                          : currentCopiedUrl
                      );
                    }}
                  />
                ) : (
                  <SvgExternalLink
                    key="open"
                    size={14}
                    className="transition-transform duration-200"
                  />
                )}
              </button>
            </Tooltip>
          )}
          <div
            data-testid="url-text-wrapper"
            className="min-w-0 flex-1 overflow-hidden"
          >
            <Tooltip tooltip={displayUrl} side="bottom" delayDuration={200}>
              {isDisplayUrlCopyable ? (
                <button
                  type="button"
                  onClick={handleCopyUrl}
                  className="block w-full min-w-0 cursor-pointer text-start focus:outline-hidden"
                  aria-label={t("copyUrl.ariaLabel", { url: displayUrl })}
                >
                  {urlText}
                </button>
              ) : (
                <div className="block w-full min-w-0 text-start">{urlText}</div>
              )}
            </Tooltip>
          </div>
        </div>
        {/* Export button — shown for downloadable file previews (e.g. markdown → docx) */}
        {onDownload && (
          <Button
            disabled={isDownloading}
            variant="action"
            prominence="tertiary"
            icon={isDownloading ? SpinningLoader : SvgExternalLink}
            onClick={onDownload}
          >
            {isDownloading ? t("export.inProgress") : t("export.button")}
          </Button>
        )}
        {/* Share button — shown when webapp preview is active */}
        {previewUrl && sessionId && (
          <ShareButton
            key={sessionId}
            sessionId={sessionId}
            webappUrl={previewUrl}
            sharingScope={sharingScope}
            onScopeChange={onScopeChange}
          />
        )}
      </div>
    </div>
  );
}
