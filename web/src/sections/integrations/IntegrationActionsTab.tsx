"use client";

import { useEffect, useState } from "react";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import UnsavedChangesModal from "@/sections/modals/UnsavedChangesModal";
import { useTranslations } from "next-intl";
import { Button, Card, InputTypeIn, MessageCard, Text } from "@opal/components";
import { ContentAction, Section, toast } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgRefreshCw } from "@opal/icons";
import { useNavigation } from "@opal/navigation";
import { integrationHref } from "@/lib/customize/paths";
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
  IntegrationActionsResponse,
  IntegrationActionsUpdate,
  PolicyValue,
} from "@/lib/integrations/types";

interface Draft {
  defaultPolicy: PolicyValue | null;
  actions: Record<string, PolicyValue | null>;
}

function savedDraft(data: IntegrationActionsResponse): Draft {
  return {
    defaultPolicy: data.default_policy,
    actions: Object.fromEntries(
      data.actions.map((action) => [action.key, action.admin_policy])
    ),
  };
}

/** The saved values with the admin's edits on top. A revalidation of `data`
 * shows the newer values of the rows the admin did not edit. */
function withEdits(saved: Draft, edits: IntegrationActionsUpdate): Draft {
  return {
    defaultPolicy:
      edits.default_policy === undefined
        ? saved.defaultPolicy
        : edits.default_policy,
    actions: { ...saved.actions, ...edits.actions },
  };
}

/** The edits that differ from the saved values. A save sends only these, so a
 * save from a stale page keeps the newer settings of the other rows. */
function changes(
  edits: IntegrationActionsUpdate,
  saved: Draft
): IntegrationActionsUpdate {
  const update: IntegrationActionsUpdate = {
    actions: Object.fromEntries(
      Object.entries(edits.actions).filter(
        ([key, value]) => key in saved.actions && value !== saved.actions[key]
      )
    ),
  };
  if (
    edits.default_policy !== undefined &&
    edits.default_policy !== saved.defaultPolicy
  )
    update.default_policy = edits.default_policy;
  return update;
}

function hasChanges(update: IntegrationActionsUpdate): boolean {
  return (
    update.default_policy !== undefined ||
    Object.keys(update.actions).length > 0
  );
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
  const [edits, setEdits] = useState<IntegrationActionsUpdate>({
    actions: {},
  });
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  // An edit that newer saved values already match is dropped, so a later
  // change of that row is not covered by it.
  useEffect(() => {
    if (data) setEdits((previous) => changes(previous, savedDraft(data)));
  }, [data]);
  const navigation = useNavigation();
  const readOnly = !integration.can_manage;
  const isMcp = integration.shape === "mcp_server";
  const dirty = data ? hasChanges(changes(edits, savedDraft(data))) : false;
  const unsavedChanges = useUnsavedChangesGuard({ isDirty: dirty });

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

  const saved = savedDraft(data);
  const current = withEdits(saved, edits);

  // An edit back to the saved value is dropped, so a later revalidation
  // shows the newer value of that row and a save leaves it as it is.
  function setDraft(next: Draft) {
    setEdits(
      changes(
        { default_policy: next.defaultPolicy, actions: next.actions },
        saved
      )
    );
  }

  // Craft asks for an action that always asks, even when it is set to Allow.
  function applied(action: IntegrationAction, value: PolicyValue): PolicyValue {
    return action.always_asks && value === "allow" ? "ask" : value;
  }

  function fallback(action: IntegrationAction): PolicyValue {
    return applied(action, current.defaultPolicy ?? action.default_policy);
  }

  const search = query.trim().toLocaleLowerCase();
  const shown = data.actions.filter((action) =>
    `${action.display_name} ${action.description ?? ""}`
      .toLocaleLowerCase()
      .includes(search)
  );
  const readActions = shown.filter((action) => action.read_only === true);
  const writeActions = shown.filter((action) => action.read_only === false);
  const otherActions = shown.filter((action) => action.read_only === null);

  function items(actions: IntegrationAction[]): PolicyEditorItem[] {
    return actions.map((action) => ({
      id: action.key,
      name: action.display_name,
      description: action.description ?? "",
      defaultPolicy: fallback(action),
      disabledPolicies: action.always_asks ? ["allow"] : undefined,
      note: action.always_asks
        ? t("alwaysAsks")
        : (current.actions[action.key] ?? null) === null
          ? t("usesDefault")
          : t("setByAdmin"),
    }));
  }

  function policies(actions: IntegrationAction[]): Record<string, PolicyValue> {
    return Object.fromEntries(
      actions.flatMap((action) => {
        const value = current.actions[action.key];
        return value ? [[action.key, applied(action, value)]] : [];
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
      const next = await updateIntegrationActions(
        integration.id,
        changes(edits, saved)
      );
      await mutate(next, { revalidate: false });
      setEdits({ actions: {} });
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
  // An individual server lists its tools with the acting admin's own
  // connection, which the Configuration tab does not hold.
  const individual = integration.auth_mode === "individual";

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
              disabled={busy || readOnly || dirty}
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
          description={
            individual
              ? t("connectFirst.individualDescription")
              : t("connectFirst.description")
          }
          rightChildren={
            individual ? (
              <Button
                prominence="secondary"
                onClick={() =>
                  navigation.go(
                    integrationHref(integration.id, "configuration")
                  )
                }
              >
                {t("connectFirst.openIntegration")}
              </Button>
            ) : (
              <Button prominence="secondary" onClick={onOpenConfiguration}>
                {t("connectFirst.open")}
              </Button>
            )
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
            {
              id: "other",
              title: t("other", { count: otherActions.length }),
              actions: otherActions,
            },
          ].map((group) =>
            group.actions.length === 0 ? null : (
              <Card key={group.id} padding={4}>
                <PolicyEditor
                  title={group.title}
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
      <UnsavedChangesModal
        open={unsavedChanges.confirmationOpen}
        onCancel={unsavedChanges.cancelLeave}
        onDiscard={unsavedChanges.discardAndLeave}
      />
    </Section>
  );
}
