"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
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
import { fetchErrorDetail } from "@/lib/fetcher";
import { useUserGroupPlugins } from "@/lib/groupPlugins/hooks";
import useUserSkills from "@/hooks/useUserSkills";
import type { CustomSkill, SkillInstallationPolicy } from "@/lib/skills/types";
import GroupPluginSettingRow from "@/views/admin/GroupsPage/GroupPluginSettingRow";
import {
  INHERIT,
  isPolicyChoice,
  useGroupPolicyOptions,
  type PolicyChoice,
} from "@/lib/skills/installationPolicy";

interface GroupPluginsTabProps {
  groupId: number;
}

/** The plugins of a group and the group's install setting of each. Each row
 * saves on its own; the group form's Save never sends them. */
export default function GroupPluginsTab({ groupId }: GroupPluginsTabProps) {
  const t = useTranslations("admin.groups.plugins");
  const { data, error, refresh, setPolicy } = useUserGroupPlugins(groupId);
  const addModal = useCreateModal();

  async function save(
    pluginId: string,
    policy: SkillInstallationPolicy | null
  ): Promise<boolean> {
    try {
      await setPolicy(pluginId, policy);
      toast.success(t("toasts.saved"));
      return true;
    } catch (saveError) {
      toast.error(fetchErrorDetail(saveError) ?? t("toasts.saveFailed"));
      return false;
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
          <Text font="main-ui-body" color="text-04" as="p">
            {t("intro")}
          </Text>
          <Text font="secondary-body" color="text-03" as="p">
            {t("inheritance")}
          </Text>
          <Text font="secondary-body" color="text-03" as="p">
            {t("conflicts")}
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
        data.map((plugin) => (
          <GroupPluginSettingRow
            key={plugin.plugin_id}
            plugin={plugin}
            onSave={save}
          />
        ))
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
  const { options } = useGroupPolicyOptions(
    selected === null || published
      ? undefined
      : (selected.company_installation_policy ?? undefined)
  );
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
