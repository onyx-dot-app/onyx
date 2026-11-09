"use client";

import { useTranslations } from "next-intl";
import { Badge, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import type { SkillMarketplace } from "@/lib/skills/types";

interface SkillMarketplaceLabelProps {
  marketplace: SkillMarketplace;
}

export default function SkillMarketplaceLabel({
  marketplace,
}: SkillMarketplaceLabelProps) {
  const t = useTranslations("skills.synced");
  return (
    <Section gap={1} height="auto" alignItems="start" className="min-w-0">
      <Badge
        title={marketplace.name}
        color="info"
        size={5}
        tooltip={t("source", { name: marketplace.name })}
      />
      {marketplace.folder && (
        <Text
          font="secondary-body"
          color="text-03"
          maxLines={1}
          overflowTooltip
        >
          {marketplace.folder}
        </Text>
      )}
    </Section>
  );
}
