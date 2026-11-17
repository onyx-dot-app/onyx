"use client";

import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  InputSingleSelect,
  MessageCard,
  Text,
} from "@opal/components";
import { ContentAction, Section } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgArrowUpRight, SvgTrash } from "@opal/icons";
import { useNavigation } from "@opal/navigation";
import type { LinkValue } from "@/lib/agents/types";
import {
  effectiveSetting,
  lockReason,
  type AgentPluginDraft,
} from "@/lib/agents/plugins";
import { useAgentPluginCatalog } from "@/lib/integrations/hooks";
import type {
  AgentCatalogIntegration,
  AgentPluginOption,
  IntegrationAction,
} from "@/lib/integrations/types";
import { integrationDetailHref } from "@/lib/integrations/utils";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";

interface SettingSelectProps {
  label: string;
  value: LinkValue;
  offerAllow: boolean;
  onChange: (value: LinkValue) => void;
}

function SettingSelect({
  label,
  value,
  offerAllow,
  onChange,
}: SettingSelectProps) {
  const t = useTranslations("agents.editor.plugins");
  const policy = useTranslations("actions.policyToggle");
  const options: { value: LinkValue; title: string }[] = [
    { value: "inherit", title: t("choice.inherit") },
    ...(offerAllow || value === "allow"
      ? [{ value: "allow" as const, title: policy("always.label") }]
      : []),
    { value: "ask", title: policy("ask.label") },
    { value: "blocked", title: policy("deny.label") },
  ];
  return (
    <InputSingleSelect
      placeholder={label}
      value={value}
      defaultOption="inherit"
      options={options}
      onValueChange={(next) => {
        const choice = options.find((option) => option.value === next);
        if (choice) onChange(choice.value);
      }}
    />
  );
}

interface ActionRowProps {
  integration: AgentCatalogIntegration;
  action: IntegrationAction;
  draft: AgentPluginDraft;
  canManageIntegrations: boolean;
  onChange: (value: LinkValue) => void;
}

function ActionRow({
  integration,
  action,
  draft,
  canManageIntegrations,
  onChange,
}: ActionRowProps) {
  const t = useTranslations("agents.editor.plugins");
  const navigation = useNavigation();
  const lock = lockReason(integration, action);
  const effective = effectiveSetting(integration, action, draft);
  const value = draft.actions[action.key] ?? "inherit";

  return (
    <Section gap={0.5} alignItems="stretch" height="auto">
      <ContentAction
        font="main-ui-action"
        title={action.display_name}
        description={action.description ?? undefined}
        padding={0}
        fillRight
        rightChildren={
          <SettingSelect
            label={t("actionSetting", { action: action.display_name })}
            value={value}
            offerAllow={lock === null}
            onChange={onChange}
          />
        }
      />
      <Text font="secondary-body" color="text-03">
        {t("effective", {
          policy: effective.policy,
          source: effective.source,
        })}
      </Text>
      {lock && (
        <Text font="secondary-body" color="text-03">
          {t(`lock.${lock}`)}
        </Text>
      )}
      {effective.policy === "ask" && (
        <Section
          flexDirection="row"
          justifyContent="between"
          gap={1}
          wrap
          height="auto"
        >
          <Text font="secondary-body" color="text-03">
            {integration.users_can_save_always_allow
              ? t("askHint")
              : t("askHintAdminOnly")}
          </Text>
          {canManageIntegrations && (
            <Button
              size="xs"
              prominence="tertiary"
              rightIcon={SvgArrowUpRight}
              {...navigation.linkTo(
                integrationDetailHref(integration.id, "actions")
              )}
            >
              {t("openIntegration", { integration: integration.name })}
            </Button>
          )}
        </Section>
      )}
    </Section>
  );
}

interface PluginCardProps {
  draft: AgentPluginDraft;
  option: AgentPluginOption | undefined;
  canManageIntegrations: boolean;
  onChange: (draft: AgentPluginDraft) => void;
  onRemove: () => void;
}

function PluginCard({
  draft,
  option,
  canManageIntegrations,
  onChange,
  onRemove,
}: PluginCardProps) {
  const t = useTranslations("agents.editor.plugins");
  const integrations = option?.integrations ?? [];
  const offerDefaultAllow = integrations.some(
    (integration) => integration.users_can_save_always_allow
  );

  function setAction(key: string, value: LinkValue) {
    const { [key]: _removed, ...rest } = draft.actions;
    onChange({
      ...draft,
      actions: value === "inherit" ? rest : { ...rest, [key]: value },
    });
  }

  return (
    <Card border="solid" rounding={4} padding={4}>
      <Section gap={4} alignItems="stretch" height="auto">
        <ContentAction
          font="main-ui-action"
          title={draft.plugin_name}
          description={option?.description ?? undefined}
          padding={0}
          rightChildren={
            <Button
              size="sm"
              prominence="tertiary"
              icon={SvgTrash}
              aria-label={t("remove", { plugin: draft.plugin_name })}
              onClick={onRemove}
            />
          }
        />
        {!option ? (
          <Text font="secondary-body" color="text-03">
            {t("notVisible")}
          </Text>
        ) : (
          <>
            <Section gap={0.5} alignItems="stretch" height="auto">
              <ContentAction
                font="main-ui-action"
                title={t("default.title")}
                description={t("default.description")}
                padding={0}
                fillRight
                rightChildren={
                  <SettingSelect
                    label={t("defaultSetting", { plugin: draft.plugin_name })}
                    value={draft.default}
                    offerAllow={offerDefaultAllow}
                    onChange={(value) => onChange({ ...draft, default: value })}
                  />
                }
              />
              {!offerDefaultAllow && (
                <Text font="secondary-body" color="text-03">
                  {t("lock.defaultFinal")}
                </Text>
              )}
            </Section>
            {integrations.map((integration) => (
              <Section
                key={integration.id}
                gap={2}
                alignItems="stretch"
                height="auto"
              >
                <Text font="main-ui-action" color="text-04">
                  {integration.name}
                </Text>
                {integration.actions.length === 0 ? (
                  <Text font="secondary-body" color="text-03">
                    {t("noActions")}
                  </Text>
                ) : (
                  integration.actions.map((action) => (
                    <ActionRow
                      key={action.key}
                      integration={integration}
                      action={action}
                      draft={draft}
                      canManageIntegrations={canManageIntegrations}
                      onChange={(value) => setAction(action.key, value)}
                    />
                  ))
                )}
              </Section>
            ))}
          </>
        )}
      </Section>
    </Card>
  );
}

interface AgentPluginsSectionProps {
  value: AgentPluginDraft[];
  onChange: (value: AgentPluginDraft[]) => void;
}

/** The plugins of an agent, each with a setting for each action. */
export default function AgentPluginsSection({
  value,
  onChange,
}: AgentPluginsSectionProps) {
  const t = useTranslations("agents.editor.plugins");
  const { data, error, isLoading, mutate } = useAgentPluginCatalog();
  const { isGlobalHolder, isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_ACTIONS
  );
  const canManageIntegrations = isGlobalHolder || isScopedManager;
  const catalog = data ?? [];
  const added = new Set(value.map((draft) => draft.plugin_id));
  const addable = catalog.filter((option) => !added.has(option.plugin_id));

  function add(pluginId: string) {
    const option = catalog.find((entry) => entry.plugin_id === pluginId);
    if (!option) return;
    onChange([
      ...value,
      {
        plugin_id: option.plugin_id,
        plugin_name: option.plugin_name,
        default: "inherit",
        actions: {},
      },
    ]);
  }

  function replace(index: number, draft: AgentPluginDraft) {
    onChange(value.map((entry, i) => (i === index ? draft : entry)));
  }

  return (
    <Section gap={2} alignItems="stretch" height="auto">
      <ContentAction
        font="main-ui-action"
        title={t("title")}
        description={t("description")}
        padding={0}
        fillRight
        rightChildren={
          !isLoading && !error && addable.length > 0 ? (
            <InputSingleSelect
              search
              placeholder={t("add")}
              value=""
              options={addable.map((option) => ({
                value: option.plugin_id,
                title: option.plugin_name,
              }))}
              onValueChange={add}
            />
          ) : undefined
        }
      />
      {isLoading ? (
        <IconLoader />
      ) : error ? (
        <MessageCard
          variant="error"
          title={t("loadFailed")}
          rightChildren={
            <Button prominence="secondary" onClick={() => void mutate()}>
              {t("retry")}
            </Button>
          }
        />
      ) : catalog.length === 0 && value.length === 0 ? (
        <Text font="secondary-body" color="text-03">
          {t("empty")}
        </Text>
      ) : null}
      {data &&
        value.map((draft, index) => (
          <PluginCard
            key={draft.plugin_id}
            draft={draft}
            option={catalog.find(
              (entry) => entry.plugin_id === draft.plugin_id
            )}
            canManageIntegrations={canManageIntegrations}
            onChange={(next) => replace(index, next)}
            onRemove={() =>
              onChange(
                value.filter((entry) => entry.plugin_id !== draft.plugin_id)
              )
            }
          />
        ))}
    </Section>
  );
}
