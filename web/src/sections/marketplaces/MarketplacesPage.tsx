"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import { SvgPlus } from "@opal/icons";
import { SvgGitHub } from "@opal/logos";
import { customizeTabHref } from "@/lib/customize/paths";
import { useMarketplaceAdded } from "@/lib/marketplaces/hooks";
import { BackLink } from "@/sections/customize/CustomizeDetailLayout";
import AddMarketplaceModal from "@/sections/marketplaces/AddMarketplaceModal";
import MarketplacesTable from "@/sections/marketplaces/MarketplacesTable";

export default function MarketplacesPage() {
  const t = useTranslations("plugins.marketplaces");
  const tabCopy = useTranslations("customize.tabs");
  const onAdded = useMarketplaceAdded();
  const [adding, setAdding] = useState(false);
  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={SvgGitHub}
        title={t("page.title")}
        description={t("page.description")}
        back={
          <BackLink
            to={customizeTabHref("plugins")}
            label={tabCopy("plugins")}
          />
        }
        actions={[
          <Button key="add" icon={SvgPlus} onClick={() => setAdding(true)}>
            {t("add.menuItem")}
          </Button>,
        ]}
      />
      <SettingsLayouts.Body>
        <MarketplacesTable />
      </SettingsLayouts.Body>
      <AddMarketplaceModal
        open={adding}
        onClose={() => setAdding(false)}
        onAdded={(marketplace) => {
          setAdding(false);
          onAdded(marketplace);
        }}
      />
    </SettingsLayouts.Root>
  );
}
