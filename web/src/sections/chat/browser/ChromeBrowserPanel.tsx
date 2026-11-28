"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { IllustrationContent, Section, toast } from "@opal/layouts";
import { SvgGlobe, SvgMonitor } from "@opal/icons";
import { IconLoader } from "@opal/loaders";
import { stopChromeShare } from "@/lib/chat/browser/api";
import type { ChromeBrowserState } from "@/lib/chat/browser/types";
import { useCurrentMessageTree } from "@/app/app/stores/useChatSessionStore";
import {
  readWaitingToolRequests,
  useToolRequestUi,
} from "@/lib/chat/toolApprovals";
import ToolApprovalCard from "@/lib/timeline/chat/message/messageComponents/ToolApprovalCard";
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
 * The user's own Chrome as the chat's browser (the Onyx extension). Onyx asks
 * for each site in the chat, so the panel shows a step to connect Chrome, an
 * idle note, or the Stop bar over a view of the agent's tab. A site that waits
 * for approval shows its card over the view.
 */
export function ChromeBrowserPanel({
  sessionId,
  chrome,
}: ChromeBrowserPanelProps) {
  const t = useTranslations("chat.chromeBrowser");
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

  async function stop() {
    setBusy(true);
    try {
      await stopChromeShare(sessionId);
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

  const { grant, installations } = data;

  if (!grant && installations.length === 0)
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

  const humanControl =
    grant?.tabs.find((tab) => tab.id === grant.current)?.controller === "human";
  return (
    <Section height="full" gap={0} alignItems="stretch" justifyContent="start">
      {grant && (
        <div className="shrink-0 border-b px-3 py-1">
          <Section flexDirection="row" justifyContent="between" gap={2}>
            <Text
              as="p"
              font="secondary-body"
              color="text-03"
              maxLines={1}
              role="status"
            >
              {humanControl ? t("using.humanControl") : t("using.title")}
            </Text>
            <Button
              variant="danger"
              prominence="secondary"
              size="sm"
              disabled={busy}
              onClick={() => void stop()}
            >
              {t("using.stop")}
            </Button>
          </Section>
        </div>
      )}
      <div className="relative min-h-0 flex-1">
        <Section gap={2} padding={4}>
          <IllustrationContent
            illustration={SvgGlobe}
            title={t("idle.title")}
            description={t("idle.description")}
            size="sm"
          />
        </Section>
        <SiteApprovals />
      </div>
    </Section>
  );
}

/**
 * The chat's pending approvals for its browser tools, over the panel's view.
 * The chat's timeline shows the same cards.
 */
function SiteApprovals() {
  const tree = useCurrentMessageTree();
  const localStatuses = useToolRequestUi((state) => state.localStatuses);
  const waiting = useMemo(
    () =>
      tree
        ? readWaitingToolRequests(tree).flatMap((item) =>
            item.kind === "approval" &&
            item.request.tool_name.startsWith("browser_")
              ? [item]
              : []
          )
        : [],
    [tree]
  );
  if (waiting.length === 0) return null;
  return (
    <div className="absolute inset-0 z-40" data-testid="chrome-site-approvals">
      <div className="absolute inset-0 bg-background-neutral-00 opacity-80" />
      <Section
        height="full"
        justifyContent="end"
        alignItems="center"
        padding={1}
        className="relative"
      >
        <div className="max-h-full w-full max-w-[28rem] overflow-y-auto">
          <Section gap={0.75} alignItems="stretch" height="auto">
            {waiting.map(({ turnIndex, request }) => (
              <ToolApprovalCard
                key={request.approval_id}
                approval={{
                  turnIndex,
                  request,
                  status: localStatuses.get(request.approval_id) ?? "pending",
                }}
              />
            ))}
          </Section>
        </div>
      </Section>
    </div>
  );
}
