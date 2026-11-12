"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  InputSingleSelect,
  Text,
  useCreateModal,
} from "@opal/components";
import {
  ConfirmationModalLayout,
  IllustrationContent,
  InputVertical,
  Section,
  toast,
} from "@opal/layouts";
import { PageLoader } from "@opal/loaders";
import { SvgBlocks, SvgPlusCircle } from "@opal/icons";
import SvgNoResult from "@opal/illustrations/no-result";
import { useUserGroupPlugins } from "@/lib/groupPlugins/hooks";
import useUserSkills from "@/hooks/useUserSkills";
import type { CustomSkill, SkillInstallationPolicy } from "@/lib/skills/types";
import type { UserGroupPlugin } from "@/lib/groupPlugins/types";
import GroupPolicyRow from "@/sections/skills/GroupPolicyRow";
import {
  INHERIT,
  fromPolicyChoice,
  isPolicyChoice,
  usePolicyOptions,
  type PolicyChoice,
} from "@/lib/skills/installationPolicy";
import { useSkillLimitCopy } from "@/lib/skills/limits";

interface GroupPluginsTabProps {
  groupId: number;
}

/** The plugins of a group and the group's install setting of each. Each row
 * saves on its own; the group form's Save never sends them. */
export default function GroupPluginsTab({ groupId }: GroupPluginsTabProps) {
  const t = useTranslations("admin.groups.plugins");
  const { describeError } = useSkillLimitCopy();
  const { data, error, refresh, setPolicy } = useUserGroupPlugins(groupId);
  const addModal = useCreateModal();
  const [savingId, setSavingId] = useState<string | null>(null);

  async function save(
    pluginId: string,
    policy: SkillInstallationPolicy | null
  ): Promise<boolean> {
    setSavingId(pluginId);
    try {
      await setPolicy(pluginId, policy);
      toast.success(t("toasts.saved"));
      return true;
    } catch (saveError) {
      toast.error(describeError(saveError, t("toasts.saveFailed")));
      return false;
    } finally {
      setSavingId(null);
    }
  }

  if (error && !data) {
    return (
      <Section height="auto" alignItems="start" gap={2}>
        <Text role="alert" color="status-error-05">
          {t("loadFailed")}
        </Text>
        <Button prominence="secondary" onClick={() => void refresh()}>
          {t("retry")}
        </Button>
      </Section>
    );
  }
  if (!data) return <PageLoader />;

  return (
    <Section height="auto" alignItems="stretch" gap={4}>
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="start"
        wrap
        height="auto"
        gap={3}
      >
        <Section
          width="auto"
          height="auto"
          alignItems="start"
          gap={1}
          className="min-w-0 max-w-full grow basis-80"
        >
          <Text font="secondary-body" color="text-03" as="p">
            {t("description")}
          </Text>
        </Section>
        <Button
          prominence="tertiary"
          icon={SvgPlusCircle}
          onClick={() => addModal.toggle(true)}
        >
          {t("add.button")}
        </Button>
      </Section>

      {data.length === 0 ? (
        <IllustrationContent
          illustration={SvgNoResult}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <Card border="solid" padding={2}>
          <Section gap={1} height="auto" alignItems="stretch">
            {data.map((plugin) => (
              <GroupPluginRow
                key={plugin.plugin_id}
                plugin={plugin}
                disabled={!plugin.can_edit || savingId !== null}
                onSave={save}
              />
            ))}
          </Section>
        </Card>
      )}

      <addModal.Provider>
        <AddGroupPluginModal
          existingIds={data.map((plugin) => plugin.plugin_id)}
          onClose={() => addModal.toggle(false)}
          onAdd={save}
        />
      </addModal.Provider>
    </Section>
  );
}

interface GroupPluginRowProps {
  plugin: UserGroupPlugin;
  disabled: boolean;
  onSave: (
    pluginId: string,
    policy: SkillInstallationPolicy | null
  ) => Promise<boolean>;
}

function GroupPluginRow({ plugin, disabled, onSave }: GroupPluginRowProps) {
  const t = useTranslations("admin.groups.plugins");
  const options = usePolicyOptions({
    inherit: { scope: "group", policy: plugin.company_installation_policy },
  });
  const saved: PolicyChoice = plugin.installation_policy ?? INHERIT;
  return (
    <GroupPolicyRow
      name={plugin.name}
      icon={SvgBlocks}
      description={t("row.access", {
        access:
          plugin.permission === null
            ? "settingOnly"
            : plugin.published
              ? "published"
              : "shared",
      })}
      value={saved}
      options={options}
      disabled={disabled}
      onChange={(choice) => {
        if (choice !== saved)
          void onSave(plugin.plugin_id, fromPolicyChoice(choice));
      }}
      onRemove={
        plugin.permission === null
          ? () => void onSave(plugin.plugin_id, null)
          : undefined
      }
    />
  );
}

interface AddGroupPluginModalProps {
  existingIds: string[];
  onClose: () => void;
  onAdd: (
    pluginId: string,
    policy: SkillInstallationPolicy | null
  ) => Promise<boolean>;
}

/** Mirror of Claude's "Add groups": one plugin and the group's setting. A
 * published plugin needs a setting, because the group gets no share. */
function AddGroupPluginModal({
  existingIds,
  onClose,
  onAdd,
}: AddGroupPluginModalProps) {
  const t = useTranslations("admin.groups.plugins");
  const { data: skills } = useUserSkills();
  const [pluginId, setPluginId] = useState("");
  const [choice, setChoice] = useState<PolicyChoice | "">("");
  const [adding, setAdding] = useState(false);

  const candidates = useMemo<CustomSkill[]>(() => {
    const existing = new Set(existingIds);
    return (skills?.customs ?? []).filter(
      (skill): skill is CustomSkill =>
        skill.source === "custom" && !existing.has(skill.id)
    );
  }, [skills, existingIds]);
  const selected = candidates.find((skill) => skill.id === pluginId) ?? null;
  const published = selected?.public_permission != null;
  const options = usePolicyOptions({
    inherit:
      selected === null || published
        ? undefined
        : {
            scope: "group",
            policy:
              selected.installation_policy ??
              selected.default_installation_policy,
          },
  });
  const canAdd =
    selected !== null && choice !== "" && !(published && choice === INHERIT);

  async function add() {
    if (!canAdd || adding) return;
    setAdding(true);
    const added = await onAdd(pluginId, choice === INHERIT ? null : choice);
    setAdding(false);
    if (added) onClose();
  }

  return (
    <ConfirmationModalLayout
      icon={SvgBlocks}
      title={t("add.title")}
      description={t("add.description")}
      onClose={onClose}
      submit={
        <Button disabled={!canAdd || adding} onClick={() => void add()}>
          {t("add.submit")}
        </Button>
      }
    >
      <Section height="auto" alignItems="stretch" gap={3}>
        <InputVertical title={t("add.plugin.label")} withLabel>
          <InputSingleSelect
            placeholder={t("add.plugin.placeholder")}
            value={pluginId}
            search
            options={candidates.map((skill) => ({
              value: skill.id,
              title: skill.name,
              description: skill.description || undefined,
              suffix:
                skill.public_permission != null
                  ? t("add.plugin.published")
                  : undefined,
            }))}
            onValueChange={(value) => {
              setPluginId(value);
              const next = candidates.find((skill) => skill.id === value);
              setChoice(next && next.public_permission == null ? INHERIT : "");
            }}
          />
        </InputVertical>
        <InputVertical title={t("add.setting.label")} withLabel>
          <InputSingleSelect
            placeholder={t("add.setting.placeholder")}
            value={choice}
            options={options}
            disabled={selected === null}
            onValueChange={(value) => {
              if (isPolicyChoice(value)) setChoice(value);
            }}
          />
        </InputVertical>
        {candidates.length === 0 && skills && (
          <Text font="secondary-body" color="text-03" as="p">
            {t("add.noCandidates")}
          </Text>
        )}
      </Section>
    </ConfirmationModalLayout>
  );
}
