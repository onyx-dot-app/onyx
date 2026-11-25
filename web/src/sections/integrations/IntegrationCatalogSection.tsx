"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, IconContainer } from "@opal/components";
import { ContentAction, Section } from "@opal/layouts";
import { SvgGitHub, SvgGoogleDrive, SvgSlack } from "@opal/logos";
import type { IconFunctionComponent } from "@opal/types";
import { SUGGESTED_MCP_PLUGINS } from "@/lib/plugins/catalog";
import AddIntegrationModal from "@/sections/integrations/AddIntegrationModal";

const LOGOS: readonly { id: string; icon: IconFunctionComponent }[] = [
  { id: "slack", icon: SvgSlack },
  { id: "github", icon: SvgGitHub },
  { id: "google_drive", icon: SvgGoogleDrive },
  ...SUGGESTED_MCP_PLUGINS,
];

interface IntegrationCatalogSectionProps {
  from: "admin" | "customize";
}

/** The foot of an integrations list: opens the catalog in the add modal. */
export default function IntegrationCatalogSection({
  from,
}: IntegrationCatalogSectionProps) {
  const t = useTranslations("admin.integrations.add.catalog");
  const [open, setOpen] = useState(false);

  return (
    <Section gap={1} alignItems="stretch" height="auto">
      <ContentAction
        font="main-ui-action"
        title={t("title")}
        description={t("description")}
        padding={0}
        rightChildren={
          <Button prominence="secondary" onClick={() => setOpen(true)}>
            {t("browse")}
          </Button>
        }
      />
      <Section
        flexDirection="row"
        justifyContent="start"
        alignItems="center"
        gap={1}
        height="auto"
      >
        {LOGOS.map((logo) => (
          <IconContainer key={logo.id} avatar="icon" icon={logo.icon} />
        ))}
      </Section>
      {open && (
        <AddIntegrationModal
          from={from}
          start={{ kind: "catalog" }}
          onClose={() => setOpen(false)}
        />
      )}
    </Section>
  );
}
