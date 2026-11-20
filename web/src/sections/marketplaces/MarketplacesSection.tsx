"use client";

import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { ContentAction, Section } from "@opal/layouts";
import { SvgPlus } from "@opal/icons";
import { SvgGitHub } from "@opal/logos";
import MarketplacesTable from "@/sections/marketplaces/MarketplacesTable";

interface MarketplacesSectionProps {
  onAdd: () => void;
}

export default function MarketplacesSection({
  onAdd,
}: MarketplacesSectionProps) {
  const t = useTranslations("plugins.marketplaces");
  return (
    <Section gap={2} alignItems="stretch" height="auto">
      <ContentAction
        font="main-content-emphasis"
        icon={SvgGitHub}
        title={t("page.title")}
        description={t("page.description")}
        padding={0}
        rightChildren={
          <Button prominence="secondary" icon={SvgPlus} onClick={onAdd}>
            {t("add.menuItem")}
          </Button>
        }
      />
      <MarketplacesTable />
    </Section>
  );
}
