"use client";

import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Button, Card, Text } from "@opal/components";
import { IllustrationContent, Section, toast } from "@opal/layouts";
import { SvgGlobe, SvgMonitor } from "@opal/icons";
import { IconLoader } from "@opal/loaders";
import { requestChromeShare, stopChromeShare } from "@/lib/chat/browser/api";
import type { ChromeBrowserState } from "@/lib/chat/browser/types";
import type { FetchError } from "@/lib/fetcher";
import type { SWRResponse } from "swr";

// The extension's content script on Onyx pages takes this and connects
// at once (extensions/chrome/src/utils/onyx-page-bridge.js).
function wakeExtension() {
  window.postMessage({ type: "onyx:browser-wake" }, window.origin);
}

interface ChromeBrowserPanelProps {
  sessionId: string;
  // The chat's Chrome state; the right panel fetches it
  chrome: SWRResponse<ChromeBrowserState, FetchError>;
}

/**
 * The user's own Chrome as the chat's browser (the Onyx extension). The
 * user's tab is the live view, so the panel shows what the chat may use: a
 * step to connect Chrome, a request to share tabs, or the shared tabs and a
 * Stop button.
 */
export function ChromeBrowserPanel({
  sessionId,
  chrome,
}: ChromeBrowserPanelProps) {
  const t = useTranslations("chat.chromeBrowser");
  const format = useFormatter();
  const { data, error, mutate } = chrome;
  const [busy, setBusy] = useState(false);
  const disconnected = !data || data.installations.length === 0;

  useEffect(() => {
    if (disconnected) wakeExtension();
  }, [disconnected]);

  function retry() {
    wakeExtension();
    void mutate();
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
      await mutate();
    } catch {
      toast.error(t("error"));
    } finally {
      setBusy(false);
    }
  }

  if (!data && !error)
    return (
      <Section padding={4}>
        <IconLoader size={20} />
      </Section>
    );

  // A failed refresh keeps the last state, so Stop stays at hand
  if (!data)
    return (
      <Section gap={2} padding={4}>
        <IllustrationContent
          illustration={SvgMonitor}
          title={t("unavailable.title")}
          description={t("unavailable.description")}
          size="sm"
        />
        <Button prominence="secondary" onClick={retry}>
          {t("retry")}
        </Button>
      </Section>
    );

  const { grant, request, installations } = data;

  if (grant)
    return (
      <Section gap={2} padding={4} alignItems="start" justifyContent="start">
        <Text as="p" font="main-ui-action" color="text-05">
          {t("shared.title", { count: grant.tabs.length })}
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          {t("shared.description", {
            until: format.dateTime(new Date(grant.expires_at * 1000), {
              hour: "numeric",
              minute: "2-digit",
            }),
          })}
        </Text>
        {grant.tabs.map((tab) => (
          <Card key={tab.id} padding={2}>
            <Section gap={0.25} alignItems="start">
              <Text
                as="p"
                font="main-ui-body"
                color="text-05"
                maxLines={1}
                overflowTooltip
              >
                {tab.title || tab.url}
              </Text>
              <Text
                as="p"
                font="secondary-body"
                color="text-03"
                maxLines={1}
                overflowTooltip
              >
                {tab.url}
              </Text>
              {tab.controller === "human" && (
                <Text as="p" font="secondary-body" color="text-04">
                  {t("shared.humanControl")}
                </Text>
              )}
            </Section>
          </Card>
        ))}
        <Text as="p" font="secondary-body" color="text-03">
          {t("shared.sites", { sites: grant.origins.join(", ") })}
        </Text>
        <Button
          variant="danger"
          prominence="secondary"
          disabled={busy}
          onClick={() => void run(() => stopChromeShare(sessionId))}
        >
          {t("shared.stop")}
        </Button>
      </Section>
    );

  if (installations.length === 0)
    return (
      <Section gap={2} padding={4}>
        <IllustrationContent
          illustration={SvgMonitor}
          title={t("connect.title")}
          description={t("connect.description")}
          size="sm"
        />
        <Button prominence="secondary" onClick={retry}>
          {t("retry")}
        </Button>
      </Section>
    );

  const pending = request === "pending";
  return (
    <Section gap={2} padding={4}>
      {pending && <IconLoader size={20} />}
      <IllustrationContent
        illustration={SvgGlobe}
        title={
          pending
            ? t("pending.title")
            : request === "denied"
              ? t("denied.title")
              : t("share.title")
        }
        description={
          pending ? t("pending.description") : t("share.description")
        }
        size="sm"
      />
      <Button
        prominence={pending ? "secondary" : "primary"}
        disabled={busy}
        onClick={() => void run(() => requestChromeShare(sessionId))}
      >
        {pending ? t("pending.again") : t("share.action")}
      </Button>
    </Section>
  );
}
