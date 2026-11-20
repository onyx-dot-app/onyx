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
  ownSetting,
  type AgentIntegrationDraft,
} from "@/lib/agents/integrations";
import type { PersonaSharingStatus } from "@/lib/agents/types";
import {
  useAgentIntegrationCatalog,
  useMemberIntegrations,
} from "@/lib/integrations/hooks";
import type {
  AgentCatalogIntegration,
  IntegrationAction,
} from "@/lib/integrations/types";
import { integrationDetailHref } from "@/lib/integrations/utils";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { usePolicyOptions } from "@/sections/actions/PolicyToggle";

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
  const t = useTranslations("agents.editor.integrations");
  const policyOptions = usePolicyOptions();
  const options: { value: SettingChoice; title: string }[] = [
    ...(offerAgentDefault
      ? [{ value: AGENT_DEFAULT, title: t("choice.agentDefault") }]
      : []),
    { value: "inherit", title: t("choice.inherit") },
    ...policyOptions
      .filter(
        (option) => option.value !== "allow" || offerAllow || value === "allow"
      )
      .map((option) => ({ value: option.value, title: option.label })),
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
  draft: AgentIntegrationDraft;
  canManageIntegrations: boolean;
  onChange: (value: SettingChoice) => void;
}

function ActionRow({
  integration,
  action,
  draft,
  canManageIntegrations,
  onChange,
}: ActionRowProps) {
  const t = useTranslations("agents.editor.integrations");
  const navigation = useNavigation();
  const lock = lockReason(integration, action);
  const effective = effectiveSetting(integration, action, draft);
  const value: SettingChoice = ownSetting(draft, action.key) ?? AGENT_DEFAULT;

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
      {lock && (
        <Text font="secondary-body" color="text-03">
          {t(`lock.${lock}`)}
        </Text>
      )}
      {effective.policy === "ask" && !action.always_asks && (
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

interface IntegrationCardProps {
  draft: AgentIntegrationDraft;
  integration: AgentCatalogIntegration | undefined;
  /** Some people who can use the agent cannot use the integration. */
  sharedWider: boolean;
  canManageIntegrations: boolean;
  onChange: (draft: AgentIntegrationDraft) => void;
  onRemove: () => void;
}

function IntegrationCard({
  draft,
  integration,
  sharedWider,
  canManageIntegrations,
  onChange,
  onRemove,
}: IntegrationCardProps) {
  const t = useTranslations("agents.editor.integrations");
  const name = draft.integration_name;

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
          title={name}
          description={integration?.description ?? undefined}
          padding={0}
          rightChildren={
            <Button
              size="sm"
              prominence="tertiary"
              icon={SvgTrash}
              aria-label={t("remove.ariaLabel", { integration: name })}
              onClick={onRemove}
            />
          }
        />
        {sharedWider && (
          <MessageCard
            variant="warning"
            title={t("sharedWider", { integration: name })}
          />
        )}
        {!integration ? (
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
                    label={t("defaultSetting.label", { integration: name })}
                    value={draft.default}
                    offerAllow={integration.users_can_save_always_allow}
                    offerAgentDefault={false}
                    onChange={(value) => {
                      if (value !== AGENT_DEFAULT)
                        onChange({ ...draft, default: value });
                    }}
                  />
                }
              />
              {!integration.users_can_save_always_allow && (
                <Text font="secondary-body" color="text-03">
                  {t("lock.adminFinal")}
                </Text>
              )}
            </Section>
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
          </>
        )}
      </Section>
    </Card>
  );
}

interface AgentIntegrationsSectionProps {
  value: AgentIntegrationDraft[];
  onChange: (value: AgentIntegrationDraft[]) => void;
  /** Who can use the agent. A link gives no access to the integration. */
  sharingStatus: PersonaSharingStatus;
}

/** The integrations of an agent, each with a setting for each action. */
export default function AgentIntegrationsSection({
  value,
  onChange,
  sharingStatus,
}: AgentIntegrationsSectionProps) {
  const t = useTranslations("agents.editor.integrations");
  const { data, error, isLoading, mutate } = useAgentIntegrationCatalog();
  const members = useMemberIntegrations();
  const { isGlobalHolder, isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_ACTIONS
  );
  const canManageIntegrations = isGlobalHolder || isScopedManager;
  const catalog = data ?? [];
  const added = new Set(value.map((draft) => draft.integration_id));
  const addable = catalog.filter((option) => !added.has(option.id));

  function add(id: string) {
    const option = catalog.find((entry) => String(entry.id) === id);
    if (!option) return;
    onChange([
      ...value,
      {
        integration_id: option.id,
        integration_name: option.name,
        default: "inherit",
        actions: {},
      },
    ]);
  }

  // An agent gives no access: a person the agent is shared with uses the
  // integration only with access of their own.
  function sharedWider(integrationId: number): boolean {
    if (sharingStatus === "PRIVATE" || members.data === undefined) return false;
    const member = members.data.find((entry) => entry.id === integrationId);
    return !member?.access.shared_with_everyone;
  }

  function replace(index: number, draft: AgentIntegrationDraft) {
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
                value: String(option.id),
                title: option.name,
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
          <IntegrationCard
            key={draft.integration_id}
            draft={draft}
            integration={catalog.find(
              (entry) => entry.id === draft.integration_id
            )}
            sharedWider={sharedWider(draft.integration_id)}
            canManageIntegrations={canManageIntegrations}
            onChange={(next) => replace(index, next)}
            onRemove={() =>
              onChange(
                value.filter(
                  (entry) => entry.integration_id !== draft.integration_id
                )
              )
            }
          />
        ))}
    </Section>
  );
}
