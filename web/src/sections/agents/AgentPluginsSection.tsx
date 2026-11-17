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
import type { LinkValue } from "@/lib/integrations/types";
import {
  effectiveSetting,
  lockReason,
  stricterPlugin,
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

/** An action with no setting of its own uses the agent default. */
const AGENT_DEFAULT = "agent_default" as const;
type SettingChoice = LinkValue | typeof AGENT_DEFAULT;

interface SettingSelectProps {
  label: string;
  value: SettingChoice;
  offerAllow: boolean;
  /** Whether "Use the agent default" is a choice: true for an action. */
  offerAgentDefault: boolean;
  onChange: (value: SettingChoice) => void;
}

function SettingSelect({
  label,
  value,
  offerAllow,
  offerAgentDefault,
  onChange,
}: SettingSelectProps) {
  const t = useTranslations("agents.editor.plugins");
  const policy = useTranslations("actions.policyToggle");
  const options: { value: SettingChoice; title: string }[] = [
    ...(offerAgentDefault
      ? [{ value: AGENT_DEFAULT, title: t("choice.agentDefault") }]
      : []),
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
      defaultOption={offerAgentDefault ? AGENT_DEFAULT : "inherit"}
      options={options}
      onValueChange={(next) => {
        const choice = options.find((option) => option.value === next);
        if (choice) onChange(choice.value);
      }}
    />
  );
}

/** An agent Ask stays when the integration allows the action, so the hint
 * names the setting that asks. */
function askHintKey(
  fromIntegration: boolean,
  usersCanSaveAlwaysAllow: boolean
): "askHint" | "askHintAdminOnly" | "askHintAgent" | "askHintAgentOnly" {
  if (fromIntegration)
    return usersCanSaveAlwaysAllow ? "askHint" : "askHintAdminOnly";
  return usersCanSaveAlwaysAllow ? "askHintAgent" : "askHintAgentOnly";
}

interface ActionRowProps {
  integration: AgentCatalogIntegration;
  action: IntegrationAction;
  draft: AgentPluginDraft;
  /** The other plugins of the agent that hold the integration. */
  others: readonly AgentPluginDraft[];
  canManageIntegrations: boolean;
  onChange: (value: SettingChoice) => void;
}

function ActionRow({
  integration,
  action,
  draft,
  others,
  canManageIntegrations,
  onChange,
}: ActionRowProps) {
  const t = useTranslations("agents.editor.plugins");
  const navigation = useNavigation();
  const lock = lockReason(integration, action);
  const stricter = stricterPlugin(integration, action, draft, others);
  const effective =
    stricter?.setting ?? effectiveSetting(integration, action, draft);
  const value: SettingChoice = draft.actions[action.key] ?? AGENT_DEFAULT;

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
            label={t("actionSetting.label", { action: action.display_name })}
            value={value}
            offerAllow={lock === null}
            offerAgentDefault
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
      {stricter && (
        <Text font="secondary-body" color="text-03">
          {t("stricterPlugin", { plugin: stricter.draft.plugin_name })}
        </Text>
      )}
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
            {t(
              askHintKey(
                effective.source === "integration",
                integration.users_can_save_always_allow
              )
            )}
          </Text>
          {canManageIntegrations && effective.source === "integration" && (
            <Button
              size="xs"
              prominence="tertiary"
              rightIcon={SvgArrowUpRight}
              {...navigation.linkTo(
                integrationDetailHref(integration.id, "actions")
              )}
            >
              {t("openIntegration.label", { integration: integration.name })}
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
  /** The other plugins of the agent that hold each integration, by id. */
  othersByIntegration: ReadonlyMap<number, readonly AgentPluginDraft[]>;
  canManageIntegrations: boolean;
  onChange: (draft: AgentPluginDraft) => void;
  onRemove: () => void;
}

function PluginCard({
  draft,
  option,
  othersByIntegration,
  canManageIntegrations,
  onChange,
  onRemove,
}: PluginCardProps) {
  const t = useTranslations("agents.editor.plugins");
  const integrations = option?.integrations ?? [];
  const offerDefaultAllow = integrations.some(
    (integration) => integration.users_can_save_always_allow
  );

  function setAction(key: string, value: SettingChoice) {
    const { [key]: _removed, ...rest } = draft.actions;
    onChange({
      ...draft,
      actions: value === AGENT_DEFAULT ? rest : { ...rest, [key]: value },
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
              aria-label={t("remove.ariaLabel", { plugin: draft.plugin_name })}
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
                    label={t("defaultSetting.label", {
                      plugin: draft.plugin_name,
                    })}
                    value={draft.default}
                    offerAllow={offerDefaultAllow}
                    offerAgentDefault={false}
                    onChange={(value) => {
                      if (value !== AGENT_DEFAULT)
                        onChange({ ...draft, default: value });
                    }}
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
                      others={(
                        othersByIntegration.get(integration.id) ?? []
                      ).filter((other) => other.plugin_id !== draft.plugin_id)}
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

  const draftsByIntegration = new Map<number, AgentPluginDraft[]>();
  for (const draft of value) {
    const option = catalog.find((entry) => entry.plugin_id === draft.plugin_id);
    for (const integration of option?.integrations ?? []) {
      draftsByIntegration.set(integration.id, [
        ...(draftsByIntegration.get(integration.id) ?? []),
        draft,
      ]);
    }
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
              placeholder={t("add.placeholder")}
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
              {t("retry.label")}
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
            othersByIntegration={draftsByIntegration}
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
