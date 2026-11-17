"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Card, InputTypeIn, MessageCard, Text } from "@opal/components";
import { ContentAction, Section, toast } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgRefreshCw } from "@opal/icons";
import PolicyEditor, {
  type PolicyEditorItem,
} from "@/sections/actions/PolicyEditor";
import PolicyToggle from "@/sections/actions/PolicyToggle";
import { useAdminIntegrationActions } from "@/lib/integrations/hooks";
import {
  refreshIntegrationActions,
  updateIntegrationActions,
} from "@/lib/integrations/svc";
import type {
  AdminIntegrationDetail,
  IntegrationAction,
  PolicyValue,
} from "@/lib/integrations/types";

interface Draft {
  defaultPolicy: PolicyValue | null;
  actions: Record<string, PolicyValue | null>;
}

interface IntegrationActionsTabProps {
  integration: AdminIntegrationDetail;
  onOpenConfiguration: () => void;
}

export default function IntegrationActionsTab({
  integration,
  onOpenConfiguration,
}: IntegrationActionsTabProps) {
  const t = useTranslations("admin.integrations.detail.actions");
  const { data, error, isLoading, mutate } = useAdminIntegrationActions(
    integration.id
  );
  const [draft, setDraft] = useState<Draft | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const readOnly = !integration.can_manage;
  const isMcp = integration.shape === "mcp_server";

  if (isLoading) return <IconLoader />;
  if (error || !data)
    return (
      <Section alignItems="start" gap={2} height="auto">
        <MessageCard variant="error" title={t("loadFailed")} />
        <Button prominence="secondary" onClick={() => void mutate()}>
          {t("retry")}
        </Button>
      </Section>
    );

  const saved: Draft = {
    defaultPolicy: data.default_policy,
    actions: Object.fromEntries(
      data.actions.map((action) => [action.key, action.admin_policy])
    ),
  };
  const current = draft ?? saved;
  const dirty =
    current.defaultPolicy !== saved.defaultPolicy ||
    data.actions.some(
      (action) =>
        (current.actions[action.key] ?? null) !==
        (saved.actions[action.key] ?? null)
    );

  function fallback(action: IntegrationAction): PolicyValue {
    return current.defaultPolicy ?? action.default_policy;
  }

  const search = query.trim().toLocaleLowerCase();
  const shown = data.actions.filter((action) =>
    `${action.display_name} ${action.description ?? ""}`
      .toLocaleLowerCase()
      .includes(search)
  );
  const readActions = shown.filter((action) => action.read_only === true);
  const writeActions = shown.filter((action) => action.read_only !== true);

  function items(actions: IntegrationAction[]): PolicyEditorItem[] {
    return actions.map((action) => ({
      id: action.key,
      name: action.display_name,
      description: action.description ?? "",
      defaultPolicy: fallback(action),
      note:
        (current.actions[action.key] ?? null) === null
          ? t("usesDefault")
          : t("setByAdmin"),
    }));
  }

  function policies(actions: IntegrationAction[]): Record<string, PolicyValue> {
    return Object.fromEntries(
      actions.flatMap((action) => {
        const value = current.actions[action.key];
        return value ? [[action.key, value]] : [];
      })
    );
  }

  function changeGroup(
    actions: IntegrationAction[],
    next: Record<string, PolicyValue>
  ) {
    setDraft({
      ...current,
      actions: {
        ...current.actions,
        ...Object.fromEntries(
          actions.map((action) => [action.key, next[action.key] ?? null])
        ),
      },
    });
  }

  function resetGroup(actions: IntegrationAction[]) {
    setDraft({
      ...current,
      actions: {
        ...current.actions,
        ...Object.fromEntries(actions.map((action) => [action.key, null])),
      },
    });
  }

  async function save() {
    setBusy(true);
    try {
      const next = await updateIntegrationActions(integration.id, {
        default_policy: current.defaultPolicy,
        actions: Object.fromEntries(
          data?.actions.map((action) => [
            action.key,
            current.actions[action.key] ?? null,
          ]) ?? []
        ),
      });
      await mutate(next, { revalidate: false });
      setDraft(null);
      toast.success(t("saved"));
    } catch (saveError) {
      toast.error(
        saveError instanceof Error ? saveError.message : t("saveFailed")
      );
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    setBusy(true);
    try {
      const next = await refreshIntegrationActions(integration.id);
      await mutate(next, { revalidate: false });
      toast.success(t("refreshed"));
    } catch (refreshError) {
      toast.error(
        refreshError instanceof Error
          ? refreshError.message
          : t("refreshFailed")
      );
    } finally {
      setBusy(false);
    }
  }

  const waitingForConnection =
    isMcp &&
    data.actions.length === 0 &&
    integration.organization_status?.state !== "connected" &&
    integration.auth_mode !== "none";

  return (
    <Section gap={4} alignItems="stretch" height="auto">
      <Section
        flexDirection="row"
        justifyContent="between"
        gap={2}
        wrap
        height="auto"
      >
        <Section width="auto" height="auto">
          <InputTypeIn
            icon="search"
            aria-label={t("search")}
            placeholder={t("search")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </Section>
        <Section flexDirection="row" width="auto" height="auto" gap={2}>
          {isMcp && (
            <Button
              prominence="secondary"
              icon={SvgRefreshCw}
              disabled={busy || readOnly}
              onClick={() => void refresh()}
            >
              {t("refresh")}
            </Button>
          )}
          <Button
            disabled={busy || readOnly || !dirty}
            onClick={() => void save()}
          >
            {busy ? t("saving") : t("save")}
          </Button>
        </Section>
      </Section>
      <Card padding={4}>
        <ContentAction
          font="main-ui-action"
          title={t("default.title")}
          description={
            current.defaultPolicy === null
              ? t("default.unset")
              : t("default.description")
          }
          padding={0}
          rightChildren={
            <Section flexDirection="row" width="auto" height="auto" gap={1}>
              {current.defaultPolicy !== null && (
                <Button
                  size="xs"
                  prominence="tertiary"
                  disabled={busy || readOnly}
                  onClick={() => setDraft({ ...current, defaultPolicy: null })}
                >
                  {t("default.clear")}
                </Button>
              )}
              <PolicyToggle
                label={t("default.title")}
                disabled={busy || readOnly}
                value={current.defaultPolicy}
                onChange={(value) =>
                  setDraft({ ...current, defaultPolicy: value })
                }
              />
            </Section>
          }
        />
      </Card>
      {waitingForConnection ? (
        <MessageCard
          variant="info"
          title={t("connectFirst.title")}
          description={t("connectFirst.description")}
          rightChildren={
            <Button prominence="secondary" onClick={onOpenConfiguration}>
              {t("connectFirst.open")}
            </Button>
          }
        />
      ) : data.actions.length === 0 ? (
        <Text font="secondary-body" color="text-03">
          {t("empty")}
        </Text>
      ) : (
        <>
          {[
            {
              id: "read",
              title: t("readOnly", { count: readActions.length }),
              actions: readActions,
            },
            {
              id: "write",
              title: t("write", { count: writeActions.length }),
              actions: writeActions,
            },
          ].map((group) =>
            group.actions.length === 0 ? null : (
              <Card key={group.id} padding={4}>
                <PolicyEditor
                  title={group.title}
                  searchable={false}
                  disabled={busy || readOnly}
                  resetLabel={t("useDefaults")}
                  onReset={() => resetGroup(group.actions)}
                  items={items(group.actions)}
                  policies={policies(group.actions)}
                  onChange={(next) => changeGroup(group.actions, next)}
                />
              </Card>
            )
          )}
        </>
      )}
    </Section>
  );
}
