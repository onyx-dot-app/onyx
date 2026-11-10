"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Card, InputSingleSelect, Text } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { SvgBlocks, SvgFolder } from "@opal/icons";
import { fetchErrorDetail } from "@/lib/fetcher";
import { useInstallationPolicyOptions } from "@/lib/skills/hooks";
import { SKILL_INSTALLATION_POLICIES } from "@/lib/skills/types";
import type {
  GroupInstallationPolicy,
  GroupMarketplaceSetting,
  GroupSkillSetting,
  GroupSkillTarget,
} from "@/lib/groupSkills/types";

const INHERIT = "INHERIT";
type PolicyChoice = GroupInstallationPolicy | typeof INHERIT;

function isPolicyChoice(value: string): value is PolicyChoice {
  return (
    value === INHERIT ||
    SKILL_INSTALLATION_POLICIES.some((policy) => policy === value)
  );
}

export type GroupSkillRow =
  | { kind: "marketplace"; setting: GroupMarketplaceSetting }
  | { kind: "skill"; setting: GroupSkillSetting };

export function groupSkillTarget(row: GroupSkillRow): GroupSkillTarget {
  return row.kind === "marketplace"
    ? { kind: "marketplace", id: row.setting.marketplace_id }
    : { kind: "skill", id: row.setting.skill_id };
}

type SaveState =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "failed"; reason: string | null };

interface GroupSkillSettingRowProps {
  row: GroupSkillRow;
  onSave: (
    target: GroupSkillTarget,
    policy: GroupInstallationPolicy | null
  ) => Promise<void>;
}

/** One install setting. It saves on its own, apart from the group form. */
export default function GroupSkillSettingRow({
  row,
  onSave,
}: GroupSkillSettingRowProps) {
  const t = useTranslations("admin.groups.skills");
  const policyOptions = useInstallationPolicyOptions();
  const { setting } = row;
  const [confirmed, setConfirmed] = useState<{
    setting: GroupSkillRow["setting"];
    policy: PolicyChoice;
  } | null>(null);
  const saved: PolicyChoice =
    confirmed?.setting === setting
      ? confirmed.policy
      : (setting.group_installation_policy ?? INHERIT);
  // A failed choice stays on show until it saves or the user picks again.
  const [draft, setDraft] = useState<PolicyChoice | null>(null);
  const [state, setState] = useState<SaveState>({ kind: "idle" });
  const savingRef = useRef(false);
  const selectRef = useRef<HTMLDivElement>(null);
  const choice = draft ?? saved;

  function policyLabel(policy: GroupInstallationPolicy): string {
    return (
      policyOptions.find((option) => option.value === policy)?.label ?? policy
    );
  }

  const company = policyLabel(setting.company_installation_policy);
  function choiceLabel(value: PolicyChoice): string {
    return value === INHERIT
      ? t("option.inherit", { policy: company })
      : policyLabel(value);
  }

  async function save(next: PolicyChoice) {
    if (savingRef.current || !setting.can_edit) return;
    if (next === saved) {
      setDraft(null);
      setState({ kind: "idle" });
      return;
    }
    savingRef.current = true;
    setDraft(next);
    setState({ kind: "saving" });
    try {
      await onSave(groupSkillTarget(row), next === INHERIT ? null : next);
      setConfirmed({ setting, policy: next });
      setDraft(null);
      setState({ kind: "saved" });
    } catch (error) {
      setState({ kind: "failed", reason: fetchErrorDetail(error) });
    } finally {
      savingRef.current = false;
    }
  }

  const options = [
    {
      value: INHERIT,
      title: t("option.inherit", { policy: company }),
      description: t("option.inheritDescription"),
    },
    ...policyOptions.map((option) => ({
      value: option.value,
      title: option.label,
      description: option.description,
    })),
  ];

  const description =
    row.kind === "marketplace"
      ? t("marketplace.followers", {
          count: row.setting.following_skill_count,
        })
      : row.setting.description || undefined;
  const origin =
    row.kind === "skill" && row.setting.marketplace_name
      ? t("skill.fromMarketplace", {
          marketplace: row.setting.marketplace_name,
        })
      : undefined;

  return (
    <Card border="solid" rounding={3} padding={3}>
      <Section
        role="group"
        aria-label={setting.name}
        alignItems="stretch"
        height="auto"
        gap={2}
      >
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
            className="min-w-0 max-w-full grow basis-60"
          >
            <Content
              icon={row.kind === "marketplace" ? SvgFolder : SvgBlocks}
              title={setting.name}
              description={description}
              suffix={origin}
              font="main-ui-action"
              descriptionMaxLines={2}
            />
          </Section>
          <Section
            ref={selectRef}
            width="auto"
            height="auto"
            alignItems="stretch"
            className="min-w-0 max-w-full grow basis-60"
          >
            <InputSingleSelect
              placeholder={t("select.label", { name: setting.name })}
              value={choice}
              defaultOption={INHERIT}
              options={options}
              disabled={!setting.can_edit}
              isError={state.kind === "failed"}
              onValueChange={(value) => {
                if (isPolicyChoice(value)) void save(value);
              }}
            />
          </Section>
        </Section>

        <Text font="secondary-body" color="text-03" as="p">
          {saved === INHERIT
            ? t("status.inherited", { policy: company })
            : t("status.overridden", {
                policy: policyLabel(saved),
                company,
              })}
        </Text>
        {!setting.can_edit && (
          <Text font="secondary-body" color="text-03" as="p">
            {t("status.readOnly")}
          </Text>
        )}
        <span
          className={
            state.kind === "saved" || state.kind === "saving"
              ? undefined
              : "sr-only"
          }
        >
          <Text
            font="secondary-body"
            color={state.kind === "saved" ? "status-success-05" : "text-03"}
            role="status"
          >
            {state.kind === "saving"
              ? t("status.saving")
              : state.kind === "saved"
                ? t("status.saved")
                : ""}
          </Text>
        </span>
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          wrap
          height="auto"
          gap={2}
          className={state.kind === "failed" ? undefined : "sr-only"}
        >
          <Section
            width="auto"
            height="auto"
            alignItems="start"
            className="min-w-0 max-w-full grow basis-60"
          >
            <Text font="secondary-body" color="status-error-05" role="alert">
              {state.kind === "failed"
                ? t("status.failed", {
                    choice: choiceLabel(choice),
                    reason: state.reason ?? t("status.failedReason"),
                  })
                : ""}
            </Text>
          </Section>
          {state.kind === "failed" && (
            <Button
              prominence="secondary"
              size="sm"
              aria-label={t("retry.label", { name: setting.name })}
              onClick={() => {
                selectRef.current
                  ?.querySelector<HTMLElement>('[role="combobox"]')
                  ?.focus();
                void save(choice);
              }}
            >
              {t("retry.button")}
            </Button>
          )}
        </Section>
      </Section>
    </Card>
  );
}
