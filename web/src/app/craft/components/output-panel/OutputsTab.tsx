"use client";

import { SWRConfig } from "swr";
import { useUser } from "@/providers/UserProvider";
import {
  createOutputThumbnailCache,
  type OutputThumbnailCache,
  readOutputThumbnailCache,
  retainOutputThumbnailCache,
} from "@/app/craft/services/outputThumbnailCache";
import { useTranslations } from "next-intl";
import { useEffect, useLayoutEffect, useState } from "react";
import { Button, Dropdown, Text } from "@opal/components";
import { SvgLoader, SvgChevronDown, SvgChevronRight } from "@opal/icons";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { isAuthStatusError, isNotFoundError } from "@/lib/fetcher";
import {
  readOutputInventorySnapshot,
  saveOutputInventorySnapshot,
  clearOutputInventorySnapshot,
} from "@/app/craft/services/outputInventorySnapshots";
import { WorkspaceHome } from "@/app/craft/components/output-panel/WorkspaceHome";
import {
  OutputTile,
  OutputFolderTile,
} from "@/app/craft/components/output-panel/OutputTile";

interface OutputsTabProps {
  sessionId: string | null;
  isActive: boolean;
  searchQuery?: string;
  onFileOpen: (path: string, fileName: string) => void;
}

export default function OutputsTab(props: OutputsTabProps) {
  const { user } = useUser();
  return (
    <OutputsScope key={user?.id ?? "anonymous"} {...props} userId={user?.id} />
  );
}

function OutputsScope(props: OutputsTabProps & { userId: string | undefined }) {
  const [{ cache, provider }] = useState(() => {
    const cache =
      readOutputThumbnailCache(props.userId) ??
      createOutputThumbnailCache(128, 16 * 1024 * 1024, props.userId);
    return { cache, provider: cache.createProvider() };
  });
  useLayoutEffect(() => {
    retainOutputThumbnailCache(props.userId, cache);
  }, [cache, props.userId]);
  return (
    <SWRConfig value={{ provider: () => provider }}>
      <OutputsBrowser key={props.sessionId} {...props} cache={cache} />
    </SWRConfig>
  );
}

function OutputsBrowser({
  sessionId,
  isActive,
  onFileOpen,
  searchQuery = "",
  userId,
  cache,
}: OutputsTabProps & {
  userId: string | undefined;
  cache: OutputThumbnailCache;
}) {
  const t = useTranslations("craft.outputsTab");
  const [folder, setFolder] = useState("");
  const [fileType, setFileType] = useState("all");
  const [snapshot, setSnapshot] = useState(() =>
    userId && sessionId
      ? readOutputInventorySnapshot(userId, sessionId)
      : undefined
  );
  const liveInventory = useBuildSessionStore((state) =>
    sessionId ? (state.sessions.get(sessionId)?.outputInventory ?? null) : null
  );
  const status = useBuildSessionStore((state) =>
    sessionId ? state.sessions.get(sessionId)?.outputInventoryStatus : undefined
  );
  const error = useBuildSessionStore((state) =>
    sessionId ? state.sessions.get(sessionId)?.outputInventoryError : undefined
  );
  const terminal = isAuthStatusError(error) || isNotFoundError(error);
  if (snapshot !== undefined && (liveInventory !== null || terminal))
    setSnapshot(undefined);
  const inventory = terminal ? null : (liveInventory ?? snapshot ?? null);
  useLayoutEffect(() => {
    cache.activateSession(sessionId);
    if (sessionId) {
      if (terminal) cache.clearSession(sessionId);
      else if (liveInventory !== null)
        cache.reconcileSession(sessionId, liveInventory, status === "complete");
    }
    return () => cache.activateSession(null);
  }, [cache, sessionId, liveInventory, status, terminal]);
  useEffect(() => {
    if (!userId || !sessionId) return;
    if (terminal) clearOutputInventorySnapshot(userId, sessionId);
    else if (liveInventory !== null && status === "complete")
      saveOutputInventorySnapshot(userId, sessionId, liveInventory);
  }, [userId, sessionId, liveInventory, status, terminal]);
  const files = Object.values(inventory ?? {}).sort((first, second) =>
    first.path.localeCompare(second.path)
  );

  const query = searchQuery.trim().toLocaleLowerCase();
  const filtered = Boolean(query) || fileType !== "all";
  const prefix = folder ? `outputs/${folder}/` : "outputs/";
  const scoped = files.filter((file) => file.path.startsWith(prefix));
  const extensionOptions = [
    ...new Set(scoped.map((file) => getOutputExtension(file.path))),
  ].sort();
  const filterLabel = (value: string) =>
    value === "all" || value === "folders"
      ? t(`filter.${value}`)
      : value === "extension:"
        ? t("filter.noExtension")
        : `.${value.slice("extension:".length)}`;
  const filterOptions = [
    "all",
    "folders",
    ...extensionOptions.map((extension) => `extension:${extension}`),
  ];
  const visibleFiles = scoped.filter((file) => {
    if (fileType === "folders") return false;
    const relative = file.path.slice(prefix.length);
    return filtered
      ? file.path.toLocaleLowerCase().includes(query) &&
          (fileType === "all" ||
            `extension:${getOutputExtension(file.path)}` === fileType)
      : !relative.includes("/");
  });
  const folders =
    fileType === "folders" || !filtered
      ? [
          ...new Set(
            scoped.flatMap((file) => {
              const relative = file.path.slice(prefix.length);
              return relative.includes("/")
                ? [relative.split("/")[0] ?? ""]
                : [];
            })
          ),
        ]
          .filter((name) => name.toLocaleLowerCase().includes(query))
          .sort()
      : [];
  const segments = folder ? folder.split("/") : [];

  return (
    <WorkspaceHome title={t("home.description")} wide>
      <div className="flex flex-wrap items-center justify-between gap-2 pb-2">
        <nav
          aria-label={t("folders.ariaLabel")}
          className="flex min-w-0 flex-wrap items-center gap-0.5"
        >
          <Button
            prominence="tertiary"
            size="xs"
            onClick={() => setFolder("")}
            aria-current={!folder ? "page" : undefined}
          >
            {t("folders.root")}
          </Button>
          {segments.map((segment, index) => (
            <div
              key={segments.slice(0, index + 1).join("/")}
              className="flex items-center gap-0.5"
            >
              <SvgChevronRight
                size={12}
                className="stroke-text-03 shrink-0"
                aria-hidden
              />
              <Button
                prominence="tertiary"
                size="xs"
                onClick={() =>
                  setFolder(segments.slice(0, index + 1).join("/"))
                }
                aria-current={
                  index === segments.length - 1 ? "page" : undefined
                }
              >
                {segment}
              </Button>
            </div>
          ))}
        </nav>
        <Dropdown align="end">
          <Dropdown.Trigger asChild>
            <Button
              prominence="tertiary"
              size="xs"
              rightIcon={SvgChevronDown}
              aria-label={t("filter.label")}
            >
              {filterLabel(fileType)}
            </Button>
          </Dropdown.Trigger>
          <Dropdown.Data
            label={t("filter.label")}
            value={fileType}
            items={filterOptions.map((type) => ({
              kind: "option",
              value: type,
              title: filterLabel(type),
            }))}
            onSelect={(option) => {
              setFileType(option.value);
            }}
          />
        </Dropdown>
      </div>
      {visibleFiles.length === 0 && folders.length === 0 ? (
        <div
          className="flex items-center justify-center gap-2 text-center"
          role="status"
        >
          {inventory === null && isActive && status !== "error" && (
            <SvgLoader
              size={20}
              className="motion-safe:animate-spin"
              aria-hidden
            />
          )}
          <Text font="main-ui-muted" color="text-03">
            {t(
              filtered && files.length > 0
                ? "filtered.empty"
                : status === "error"
                  ? "error.description"
                  : status === "partial"
                    ? "incomplete.description"
                    : inventory !== null
                      ? "empty.description"
                      : isActive
                        ? "loading.label"
                        : "unavailable.description"
            )}
          </Text>
        </div>
      ) : (
        <div className="flex w-full flex-col gap-3">
          {folders.length > 0 && (
            <div className="grid grid-cols-2 gap-2 @[24rem]:grid-cols-3">
              {folders.map((name) => (
                <OutputFolderTile
                  key={name}
                  name={name}
                  onOpen={() => setFolder(folder ? `${folder}/${name}` : name)}
                />
              ))}
            </div>
          )}
          {sessionId && visibleFiles.length > 0 && (
            <div className="grid grid-cols-2 gap-2 @[24rem]:grid-cols-3">
              {visibleFiles.map((file) => (
                <OutputTile
                  key={file.path}
                  sessionId={sessionId}
                  file={file}
                  showPath={filtered}
                  isActive={isActive && liveInventory !== null}
                  onFileOpen={onFileOpen}
                />
              ))}
            </div>
          )}
        </div>
      )}
      {files.length > 0 && (status === "error" || status === "partial") && (
        <div role="status" className="pt-2 text-center">
          <Text font="secondary-body" color="text-03">
            {t(
              status === "error"
                ? "error.description"
                : "incomplete.description"
            )}
          </Text>
        </div>
      )}
    </WorkspaceHome>
  );
}

function getOutputExtension(path: string): string {
  return /\.([^./]+)$/.exec(path)?.[1]?.toLowerCase() ?? "";
}
