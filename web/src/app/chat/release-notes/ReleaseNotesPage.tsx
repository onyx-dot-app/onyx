"use client";

import useSWR from "swr";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SvgLoader, SvgAlertCircle } from "@opal/icons";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import {
  SvgBookOpen,
  SvgRefreshCw,
  SvgExternalLink,
  SvgChevronDownSmall,
  SvgCheck,
} from "@opal/icons";
import Settings from "@/layouts/settings-pages";
import { useCallback, useEffect, useRef, useState } from "react";
import { GITHUB_RELEASES_URL } from "@/lib/constants";
import IconButton from "@/refresh-components/buttons/IconButton";
import Separator from "@/refresh-components/Separator";
import {
  Popover,
  PopoverContent,
  PopoverMenu,
  PopoverTrigger,
} from "@/components/ui/popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";

interface ReleaseNoteItem {
  id: string;
  title: string;
  url: string;
  contentMarkdown: string;
}

interface ReleaseNotesResponse {
  sourceUrl: string;
  fetchedAt: string;
  total: number;
  offset: number;
  limit: number;
  items: ReleaseNoteItem[];
  error?: string;
}

function openExternalLink(url: string) {
  window.open(url, "_blank", "noopener,noreferrer");
}

function areReleaseNotesEquivalent(
  a: ReleaseNotesResponse,
  b: ReleaseNotesResponse
) {
  // Intentionally ignore `fetchedAt` so "Refresh" doesn't visually update if content is unchanged.
  if (a.sourceUrl !== b.sourceUrl) return false;
  if (a.total !== b.total) return false;
  if (a.offset !== b.offset) return false;
  if (a.limit !== b.limit) return false;
  if (a.items.length !== b.items.length) return false;

  for (let i = 0; i < a.items.length; i++) {
    const ai = a.items[i]!;
    const bi = b.items[i]!;
    if (
      ai.id !== bi.id ||
      ai.title !== bi.title ||
      ai.url !== bi.url ||
      ai.contentMarkdown !== bi.contentMarkdown
    ) {
      return false;
    }
  }

  return true;
}

export default function ReleaseNotesPage() {
  const REFRESH_COOLDOWN_MS = 30_000;
  const [refreshCoolingDown, setRefreshCoolingDown] = useState(false);
  const cooldownTimeoutRef = useRef<number | null>(null);
  const [versionPopoverOpen, setVersionPopoverOpen] = useState(false);
  const [versionSearchQuery, setVersionSearchQuery] = useState("");
  const [hasUserSelectedVersion, setHasUserSelectedVersion] = useState(false);
  const [selectedReleaseId, setSelectedReleaseId] = useState<string | null>(
    null
  );

  useEffect(() => {
    return () => {
      if (cooldownTimeoutRef.current !== null) {
        window.clearTimeout(cooldownTimeoutRef.current);
      }
    };
  }, []);

  const swrKeyBase = "/api/release-notes?limit=200&offset=0";
  const { data, error, isLoading, mutate } = useSWR<ReleaseNotesResponse>(
    swrKeyBase,
    errorHandlingFetcher
  );

  const items = data?.items ?? [];
  const effectiveSelectedReleaseId =
    selectedReleaseId ?? (items.length ? items[0]!.id : null);
  const displayedItems = effectiveSelectedReleaseId
    ? items.filter((i) => i.id === effectiveSelectedReleaseId)
    : [];

  const selectedReleaseTitle =
    (effectiveSelectedReleaseId
      ? items.find((i) => i.id === effectiveSelectedReleaseId)?.title
      : null) ?? null;

  const filteredVersionItems =
    versionSearchQuery.trim().length === 0
      ? items
      : items.filter((i) =>
          i.title.toLowerCase().includes(versionSearchQuery.toLowerCase())
        );

  useEffect(() => {
    // Default to the latest version (first item) until the user explicitly picks something.
    if (hasUserSelectedVersion) return;
    if (!items.length) return;
    setSelectedReleaseId(items[0]!.id);
  }, [items, hasUserSelectedVersion]);

  useEffect(() => {
    // If the selected version disappears after a refresh, fall back to the latest (if available).
    if (!selectedReleaseId) return;
    if (items.some((i) => i.id === selectedReleaseId)) return;
    setSelectedReleaseId(items[0]?.id ?? null);
  }, [items, selectedReleaseId]);

  const hardRefresh = useCallback(() => {
    if (refreshCoolingDown) return;
    setRefreshCoolingDown(true);
    if (cooldownTimeoutRef.current !== null) {
      window.clearTimeout(cooldownTimeoutRef.current);
    }
    cooldownTimeoutRef.current = window.setTimeout(() => {
      setRefreshCoolingDown(false);
    }, REFRESH_COOLDOWN_MS);

    const cacheBustingUrl = `${swrKeyBase}&force=true&ts=${Date.now()}`;
    void mutate(
      async (current) => {
        const fresh = (await errorHandlingFetcher(
          cacheBustingUrl
        )) as ReleaseNotesResponse;

        if (!current) return fresh;
        return areReleaseNotesEquivalent(current, fresh) ? current : fresh;
      },
      { revalidate: false }
    );
  }, [refreshCoolingDown]);

  const errorMessage =
    (error as Error | undefined)?.message ||
    data?.error ||
    (data && !data.items ? "Invalid response from server." : undefined);

  return (
    <Settings.Root
      data-testid="ReleaseNotesPage/container"
      aria-label="Release Notes"
    >
      <Settings.Header
        icon={SvgBookOpen}
        title="Release Notes"
        description={
          <div className="flex flex-col gap-1">
            {data?.fetchedAt && (
              <Text secondaryBody text03>
                Last updated {new Date(data.fetchedAt).toLocaleString()}
              </Text>
            )}
          </div>
        }
        rightChildren={
          <div className="flex gap-2">
            <Button
              onClick={() => openExternalLink(GITHUB_RELEASES_URL)}
              leftIcon={SvgExternalLink}
              secondary
            >
              Full Changelog
            </Button>
            <Button
              leftIcon={SvgRefreshCw}
              onClick={hardRefresh}
              disabled={refreshCoolingDown}
            >
              {refreshCoolingDown ? "Recently Refreshed" : "Refresh Contents"}
            </Button>
          </div>
        }
      >
        <div className="flex flex-row items-center gap-2 pb-2">
          <Popover
            open={versionPopoverOpen}
            onOpenChange={(open) => {
              setVersionPopoverOpen(open);
              if (!open) setVersionSearchQuery("");
            }}
          >
            <PopoverTrigger asChild>
              <Button
                secondary
                rightIcon={SvgChevronDownSmall}
                disabled={!items.length}
              >
                {selectedReleaseTitle ?? "Select version"}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="start">
              <PopoverMenu medium>
                {[
                  <InputTypeIn
                    key="version-search"
                    internal
                    leftSearchIcon
                    placeholder="Search versions..."
                    value={versionSearchQuery}
                    onChange={(e) => setVersionSearchQuery(e.target.value)}
                  />,
                  ...filteredVersionItems.map((item) => (
                    <LineItem
                      key={item.id}
                      icon={
                        effectiveSelectedReleaseId === item.id
                          ? SvgCheck
                          : undefined
                      }
                      selected={effectiveSelectedReleaseId === item.id}
                      emphasized
                      onClick={() => {
                        setHasUserSelectedVersion(true);
                        setSelectedReleaseId(item.id);
                        setVersionPopoverOpen(false);
                      }}
                    >
                      {item.title}
                    </LineItem>
                  )),
                ]}
              </PopoverMenu>
            </PopoverContent>
          </Popover>
        </div>
      </Settings.Header>

      <Settings.Body>
        {isLoading && !data ? (
          <div className="w-full flex flex-col items-center justify-center py-12 gap-3">
            <SvgLoader className="h-6 w-6 animate-spin stroke-text-03" />
            <Text text03 secondaryBody>
              Loading release notes…
            </Text>
          </div>
        ) : errorMessage ? (
          <div className="w-full flex flex-col items-center justify-center py-12 gap-3">
            <SvgAlertCircle className="h-6 w-6 stroke-action-danger-05" />
            <Text text03 secondaryBody className="text-center max-w-xl">
              {errorMessage}
            </Text>
            <Button onClick={() => mutate()}>Try again</Button>
          </div>
        ) : displayedItems.length ? (
          <div className="flex flex-col gap-8">
            {displayedItems.map((item, idx) => (
              <div key={item.id} className="flex flex-col">
                <div className="flex flex-col gap-2">
                  <div className="flex flex-row items-baseline justify-between gap-4">
                    <Text headingH2>{item.title}</Text>
                    <IconButton
                      icon={SvgExternalLink}
                      tertiary
                      tooltip="Open in new tab"
                      aria-label={`Open ${item.title} in a new tab`}
                      onClick={() => openExternalLink(item.url)}
                    />
                  </div>
                  <MinimalMarkdown content={item.contentMarkdown} />
                </div>

                {idx < displayedItems.length - 1 && (
                  <Separator noPadding className="mt-8" />
                )}
              </div>
            ))}
          </div>
        ) : (
          <Text
            className="w-full h-full flex flex-col items-center justify-center py-12"
            text03
            secondaryBody
          >
            No release notes found
          </Text>
        )}
      </Settings.Body>
    </Settings.Root>
  );
}
