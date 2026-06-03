"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Button, Text } from "@opal/components";
import {
  IllustrationContent,
  PageLoader,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { SvgPlus, SvgZap } from "@opal/icons";
import { createFlow } from "@/app/flows/api";
import { FlowStatusBadge } from "@/app/flows/components/StatusBadge";
import { FLOWS_API_BASE, flowDetailPath } from "@/app/flows/constants";
import { blankNode } from "@/app/flows/specEdits";
import type { FlowSpec, FlowSummary } from "@/app/flows/types";
import { errorHandlingFetcher } from "@/lib/fetcher";

/** A new flow opens on one HTTP node, which is a graph you can already run. */
function starterSpec(): FlowSpec {
  return { spec_version: 1, start: "http", nodes: [blankNode("http", "HTTP")] };
}

export default function FlowsListPage() {
  const t = useTranslations("flows.list");
  const router = useRouter();
  const [creating, setCreating] = useState(false);

  const {
    data: flows,
    error,
    isLoading,
  } = useSWR<FlowSummary[]>(FLOWS_API_BASE, errorHandlingFetcher);

  const handleCreate = useCallback(() => {
    setCreating(true);
    void (async () => {
      try {
        const created = await createFlow({
          name: t("defaultName"),
          spec: starterSpec(),
        });
        router.push(flowDetailPath(created.id));
      } catch (caught) {
        toast.error(
          caught instanceof Error ? caught.message : t("createFailed")
        );
        setCreating(false);
      }
    })();
  }, [router, t]);

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgZap}
        title={t("title")}
        description={t("description")}
        actions={[
          <Button
            key="create"
            variant="default"
            prominence="primary"
            icon={SvgPlus}
            disabled={creating}
            onClick={handleCreate}
          >
            {t("actions.create")}
          </Button>,
        ]}
      />
      <SettingsLayouts.Body>
        {isLoading ? <PageLoader /> : null}

        {error !== undefined ? (
          <Text font="main-content-body" color="text-04">
            {t("loadFailed")}
          </Text>
        ) : null}

        {flows !== undefined && flows.length === 0 ? (
          <IllustrationContent
            illustration={SvgNoResult}
            title={t("empty.title")}
            description={t("empty.description")}
          />
        ) : null}

        {flows !== undefined && flows.length > 0 ? (
          <div className="flex flex-col gap-2">
            {flows.map((flow) => (
              <FlowRow key={flow.id} flow={flow} />
            ))}
          </div>
        ) : null}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

function FlowRow({ flow }: { flow: FlowSummary }) {
  const t = useTranslations("flows.list");
  const router = useRouter();

  return (
    <div
      role="button"
      tabIndex={0}
      data-testid={`flow-row-${flow.id}`}
      onClick={() => router.push(flowDetailPath(flow.id))}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          router.push(flowDetailPath(flow.id));
        }
      }}
      className="flex flex-row items-center gap-3 p-3 rounded-12 border border-border-01 bg-background-neutral-00 cursor-pointer hover:border-border-02 focus-visible:outline-2 focus-visible:outline-action-selection-05"
    >
      <div className="flex flex-col gap-0.5 min-w-0 grow">
        <div className="min-w-0 truncate">
          <Text
            font="main-ui-action"
            color="text-05"
            wordWrap="whitespace-nowrap"
          >
            {flow.name}
          </Text>
        </div>
        <Text font="figure-small-label" color="text-03">
          {t("nodeCount", { count: flow.node_count })}
        </Text>
      </div>
      <FlowStatusBadge status={flow.status} />
    </div>
  );
}
