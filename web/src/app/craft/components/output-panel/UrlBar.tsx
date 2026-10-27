"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Button, InputTypeIn, Text, Tooltip } from "@opal/components";
import { SvgDownloadCloud, SvgExternalLink, SvgRevert } from "@opal/icons";
import { IconLoader } from "@opal/loaders";
import ShareButton from "@/app/craft/components/ShareButton";
import type { SharingScope } from "@/app/craft/types/streamingTypes";

export interface UrlBarProps {
  displayUrl: string;
  searchValue?: string;
  onSearchChange?: (value: string) => void;
  placeholder?: string;
  refreshLabel?: string;
  previewUrl?: string | null;
  uploadAction?: ReactNode;
  onDownloadRaw?: () => void;
  downloadRawTooltip?: string;
  onDownload?: () => void;
  isDownloading?: boolean;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  isUserRefreshing?: boolean;
  sessionId?: string;
  sharingScope?: SharingScope;
  onScopeChange?: () => void;
}

export default function UrlBar({
  displayUrl,
  searchValue,
  onSearchChange,
  placeholder,
  refreshLabel,
  previewUrl,
  uploadAction,
  onDownloadRaw,
  downloadRawTooltip,
  onDownload,
  isDownloading = false,
  onRefresh,
  isRefreshing = false,
  isUserRefreshing = false,
  sessionId,
  sharingScope = "private",
  onScopeChange,
}: UrlBarProps) {
  const t = useTranslations("craft.urlBar");
  const reloadLabel = refreshLabel ?? t("refresh.ariaLabel");
  return (
    <div className="flex h-11 shrink-0 items-center gap-2 px-3 pb-2">
      <Button
        icon={isUserRefreshing ? IconLoader : SvgRevert}
        prominence="tertiary"
        size="sm"
        disabled={!onRefresh || isRefreshing || isUserRefreshing}
        onClick={onRefresh}
        tooltip={reloadLabel}
        aria-label={reloadLabel}
        aria-busy={isRefreshing || isUserRefreshing}
      />
      <div
        data-testid="url-bar-pill"
        className="flex h-8 min-w-0 flex-1 items-center rounded-md bg-background-tint-02 px-2 overflow-hidden"
      >
        {onSearchChange ? (
          <InputTypeIn
            variant="internal"
            searchIcon
            value={searchValue ?? ""}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={placeholder}
            aria-label={placeholder}
          />
        ) : (
          <Tooltip tooltip={displayUrl} side="bottom">
            <div className="min-w-0 flex-1" data-testid="url-text-wrapper">
              <Text
                as="p"
                dir="ltr"
                font="secondary-body"
                color="text-03"
                maxLines={1}
              >
                {displayUrl}
              </Text>
            </div>
          </Tooltip>
        )}
      </div>
      {uploadAction}
      {onDownloadRaw && (
        <Button
          icon={SvgDownloadCloud}
          prominence="tertiary"
          size="sm"
          onClick={onDownloadRaw}
          tooltip={downloadRawTooltip ?? t("downloadFile.tooltip")}
          aria-label={downloadRawTooltip ?? t("downloadFile.tooltip")}
        >
          {t("downloadFile.label")}
        </Button>
      )}
      {onDownload && (
        <Button
          prominence="tertiary"
          size="sm"
          disabled={isDownloading}
          icon={isDownloading ? IconLoader : SvgExternalLink}
          onClick={onDownload}
        >
          {t(isDownloading ? "export.inProgress" : "export.button")}
        </Button>
      )}
      {previewUrl && (
        <Button
          icon={SvgExternalLink}
          prominence="tertiary"
          size="sm"
          tooltip={t("openInNewTab.tooltip")}
          aria-label={t("openInNewTab.tooltip")}
          onClick={() =>
            window.open(previewUrl, "_blank", "noopener,noreferrer")
          }
        />
      )}
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
  );
}
