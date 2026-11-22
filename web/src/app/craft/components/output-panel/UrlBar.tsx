"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { SvgDownloadCloud, SvgExternalLink } from "@opal/icons";
import { IconLoader } from "@opal/loaders";
import { PanelUrlBar } from "@/sections/output-panel/PanelUrlBar";
import ShareButton from "@/app/craft/components/ShareButton";
import type { SharingScope } from "@/app/craft/types/streamingTypes";

interface UrlBarProps {
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

/** Craft's URL bar: the shared bar with its reload, upload, download and share actions. */
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
    <PanelUrlBar
      displayUrl={displayUrl}
      searchValue={searchValue}
      onSearchChange={onSearchChange}
      placeholder={placeholder}
      refresh={{
        label: reloadLabel,
        onRefresh,
        isRefreshing,
        isUserRefreshing,
      }}
    >
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
    </PanelUrlBar>
  );
}
