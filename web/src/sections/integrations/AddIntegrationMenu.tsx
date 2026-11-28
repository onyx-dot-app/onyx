"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Dropdown } from "@opal/components";
import { SvgBookOpen, SvgCodeFile, SvgPlus, SvgServer } from "@opal/icons";
import { useNavigation, useSearchParams } from "@opal/navigation";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  customizeTabHref,
  parseNewIntegrationPrefill,
} from "@/lib/customize/paths";
import AddIntegrationModal, {
  type AddIntegrationStart,
} from "@/sections/integrations/AddIntegrationModal";

interface AddIntegrationMenuProps {
  from: "admin" | "customize";
  /** The `/new` route: the modal opens at once, filled from the URL. */
  openOnLoad?: boolean;
}

/** The Add button of an integrations list: MCP server, custom API or the
 * catalog, each in the add modal. */
export default function AddIntegrationMenu({
  from,
  openOnLoad = false,
}: AddIntegrationMenuProps) {
  const t = useTranslations("admin.integrations.add");
  const navigation = useNavigation();
  const prefill = parseNewIntegrationPrefill(useSearchParams());
  const [start, setStart] = useState<AddIntegrationStart | null>(
    openOnLoad
      ? prefill
        ? { kind: "prefill", prefill }
        : { kind: "mcp_server" }
      : null
  );

  function close() {
    setStart(null);
    if (openOnLoad)
      navigation.go(
        from === "admin"
          ? ADMIN_ROUTES.INTEGRATIONS.path
          : customizeTabHref("integrations")
      );
  }

  return (
    <>
      <Dropdown align="end" width={60}>
        <Dropdown.Trigger asChild>
          <Button icon={SvgPlus}>{t("label")}</Button>
        </Dropdown.Trigger>
        <Dropdown.Data
          label={t("label")}
          items={[
            {
              kind: "action",
              id: "mcp_server",
              icon: SvgServer,
              title: t("menu.mcpServer"),
              onSelect: () => setStart({ kind: "mcp_server" }),
            },
            {
              kind: "action",
              id: "api",
              icon: SvgCodeFile,
              title: t("menu.customApi"),
              onSelect: () => setStart({ kind: "api" }),
            },
            {
              kind: "action",
              id: "catalog",
              icon: SvgBookOpen,
              title: t("menu.fromCatalog"),
              onSelect: () => setStart({ kind: "catalog" }),
            },
          ]}
        />
      </Dropdown>
      {start && (
        <AddIntegrationModal from={from} start={start} onClose={close} />
      )}
    </>
  );
}
