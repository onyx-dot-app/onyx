"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Button, Card, Text } from "@opal/components";
import { SvgShare } from "@opal/icons";
import { Section } from "@opal/layouts";
import type { RichStr } from "@opal/types";
import type { SkillSharingDraft } from "@/lib/skills/sharing";

interface SkillSharingSummaryProps {
  title: string | RichStr;
  draft: SkillSharingDraft;
  count: number;
  configureLabel: string | RichStr;
  disabled?: boolean;
  onConfigure: () => void;
  children?: ReactNode;
}

export default function SkillSharingSummary({
  title,
  draft,
  count,
  configureLabel,
  disabled = false,
  onConfigure,
  children,
}: SkillSharingSummaryProps) {
  const t = useTranslations("skills.sharingSummary");
  const grants = draft.user_shares.length + draft.group_shares.length;
  return (
    <Card border="solid" padding={2}>
      <Section gap={2} height="auto" alignItems="stretch">
        <Section flexDirection="row" height="auto" justifyContent="between">
          <Text font="main-ui-action">{title}</Text>
          <Button
            prominence="secondary"
            size="sm"
            icon={SvgShare}
            disabled={disabled}
            onClick={onConfigure}
          >
            {configureLabel}
          </Button>
        </Section>
        {children}
        <Text font="secondary-body" color="text-03">
          {draft.public_permission !== null
            ? t("organization", { count })
            : grants > 0
              ? t("selected", {
                  users: draft.user_shares.length,
                  groups: draft.group_shares.length,
                })
              : t("private", { count })}
        </Text>
      </Section>
    </Card>
  );
}
