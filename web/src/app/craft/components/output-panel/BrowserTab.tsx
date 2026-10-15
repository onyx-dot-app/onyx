"use client";

import { useEffect, useEffectEvent, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, SelectCard, Text, Tooltip } from "@opal/components";
import { SvgGlobe, SvgLoader } from "@opal/icons";
import { cn } from "@opal/utils";

import type { RegisteredWebapp, AppDiscoveryState } from "@/lib/build/types";
import { WorkspaceHome } from "@/app/craft/components/output-panel/WorkspaceHome";

interface BrowserTabProps {
  resourceId: string;
  onLoadingChange?: (id: string, loading: boolean) => void;
  apps: RegisteredWebapp[];
  appId: string | null;
  discoveryState: AppDiscoveryState;
  refreshKey?: number;
  accessRevoked?: boolean;
  onNavigate: (appId: string | null) => void;
}

export default function BrowserTab({
  resourceId,
  onLoadingChange,
  apps,
  appId,
  discoveryState,
  refreshKey = 0,
  accessRevoked = false,
  onNavigate,
}: BrowserTabProps) {
  const t = useTranslations("craft.browserTab");
  const reportLoading = useEffectEvent((id: string, loading: boolean) => {
    onLoadingChange?.(id, loading);
  });
  useEffect(() => () => reportLoading(resourceId, false), [resourceId]);
  const app = apps.find((candidate) => candidate.id === appId);
  const [lastReadyApp, setLastReadyApp] = useState<RegisteredWebapp | null>(
    null
  );
  if (accessRevoked && lastReadyApp !== null) setLastReadyApp(null);
  else if (!accessRevoked && app?.state === "ready" && app !== lastReadyApp)
    setLastReadyApp(app);
  // Keep the accepted frame alive through temporary discovery failures.
  const frameApp =
    app?.state === "ready"
      ? app
      : lastReadyApp && (appId === null || lastReadyApp.id === appId)
        ? lastReadyApp
        : null;
  const hasFrame = !accessRevoked && frameApp !== null;
  useEffect(() => {
    if (!hasFrame) reportLoading(resourceId, false);
  }, [hasFrame, resourceId]);

  const home =
    appId === null ? (
      <WorkspaceHome title={t("home.title")}>
        {discoveryState === "checking" && apps.length === 0 ? (
          <div className="flex items-center gap-2" role="status">
            <SvgLoader size={20} className="motion-safe:animate-spin" />
            <Text font="main-ui-muted">{t("checking.label")}</Text>
          </div>
        ) : null}
        {discoveryState === "unavailable" || discoveryState === "failed" ? (
          <div role="status" className="max-w-sm">
            <Text font="main-ui-muted" color="text-03">
              {t(
                discoveryState === "failed"
                  ? "failed.description"
                  : "unavailable.description"
              )}
            </Text>
          </div>
        ) : null}
        {discoveryState === "ready" && apps.length === 0 ? (
          <div className="flex max-w-sm flex-col gap-2">
            <Text font="main-ui-body">{t("empty.title")}</Text>
            <Text font="main-ui-muted" color="text-03">
              {t("empty.description")}
            </Text>
          </div>
        ) : null}
        <div className="flex w-full flex-col gap-1.5">
          {apps.map((candidate) => (
            <Tooltip key={candidate.id} tooltip={candidate.url} side="bottom">
              <SelectCard
                role="button"
                tabIndex={0}
                aria-label={candidate.name}
                state="filled"
                border="none"
                padding={3}
                rounding={3}
                onClick={() => onNavigate(candidate.id)}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <SvgGlobe
                    size={20}
                    className="shrink-0 stroke-text-03"
                    aria-hidden
                  />
                  <div className="flex min-w-0 flex-col">
                    <Text
                      font="main-ui-muted"
                      color="text-04"
                      maxLines={2}
                      as="p"
                      wordWrap="wrap-anywhere"
                    >
                      {candidate.name}
                    </Text>
                    {candidate.state !== "ready" && (
                      <Text
                        font="secondary-body"
                        color="text-03"
                        as="p"
                        wordWrap="wrap-anywhere"
                      >
                        {t(
                          candidate.state === "starting"
                            ? "starting.label"
                            : "unavailable.label"
                        )}
                      </Text>
                    )}
                  </div>
                </div>
              </SelectCard>
            </Tooltip>
          ))}
        </div>
      </WorkspaceHome>
    ) : null;

  const unavailable =
    discoveryState === "unavailable" ||
    discoveryState === "failed" ||
    !app ||
    app.state !== "ready";
  const frameCovered = appId === null || unavailable;
  return (
    <div className="relative h-full min-h-0 bg-background-neutral-01">
      {!accessRevoked && frameApp && (
        <BrowserFrame
          key={`${frameApp.url}:${refreshKey}`}
          app={frameApp}
          covered={frameCovered}
          resourceId={resourceId}
          onLoadingChange={onLoadingChange}
        />
      )}
      {home}
      {appId !== null && unavailable && (
        <div
          className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center bg-background-neutral-01"
          role="status"
        >
          {app?.state === "starting" ? (
            <SvgLoader size={28} className="motion-safe:animate-spin" />
          ) : (
            <SvgGlobe size={28} />
          )}
          <Text font="main-ui-muted" color="text-03">
            {t(
              app?.state === "starting"
                ? "starting.label"
                : "unavailable.description"
            )}
          </Text>
          {unavailable && (
            <Button
              prominence="secondary"
              size="sm"
              onClick={() => onNavigate(null)}
            >
              {t("home.action")}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

interface BrowserFrameProps {
  app: RegisteredWebapp;
  covered: boolean;
  resourceId: string;
  onLoadingChange?: (id: string, loading: boolean) => void;
}

/** Each navigation mounts a fresh frame; its load state belongs to that frame. */
function BrowserFrame({
  app,
  covered,
  resourceId,
  onLoadingChange,
}: BrowserFrameProps) {
  const t = useTranslations("craft.browserTab");
  const [loaded, setLoaded] = useState(false);
  const reportLoading = useEffectEvent((loading: boolean) => {
    onLoadingChange?.(resourceId, loading);
  });
  useEffect(() => {
    reportLoading(!covered && !loaded);
  }, [resourceId, covered, loaded]);

  return (
    <>
      <iframe
        src={app.url}
        onLoad={() => setLoaded(true)}
        className={cn(
          "absolute inset-0 h-full w-full border-0",
          covered && "invisible pointer-events-none"
        )}
        aria-hidden={covered}
        inert={covered || !loaded}
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-top-navigation-by-user-activation"
        title={app.name}
      />
      {!covered && !loaded && (
        <div
          className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center bg-background-neutral-01"
          role="status"
        >
          <SvgLoader size={28} className="motion-safe:animate-spin" />
          <Text font="main-ui-muted" color="text-03">
            {t("loading.label")}
          </Text>
        </div>
      )}
    </>
  );
}
