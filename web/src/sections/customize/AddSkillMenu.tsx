"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Dropdown, type DropdownMenuItem } from "@opal/components";
import { SvgEdit, SvgPlus, SvgSettings, SvgUploadCloud } from "@opal/icons";
import { SvgGitHub } from "@opal/logos";
import { useNavigation } from "@opal/navigation";
import { MARKETPLACES_PATH, newSkillHref } from "@/lib/customize/paths";
import { useMarketplaceAdded } from "@/lib/marketplaces/hooks";
import { stageSkillCreationDraft } from "@/lib/skills/creationDraft";
import { useRefreshSkillLists } from "@/lib/skills/hooks";
import CreateSkillModal from "@/sections/modals/skills/CreateSkillModal";
import AddMarketplaceModal from "@/sections/marketplaces/AddMarketplaceModal";
import UploadPluginFlow from "@/sections/modals/plugins/UploadPluginFlow";

interface AddSkillMenuProps {
  upload?: "skill" | "plugin";
}

export default function AddSkillMenu({ upload = "skill" }: AddSkillMenuProps) {
  const t = useTranslations("customize.skills.add");
  const navigation = useNavigation();
  const revalidate = useRefreshSkillLists();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [pluginUploadOpen, setPluginUploadOpen] = useState(false);
  const [marketplaceOpen, setMarketplaceOpen] = useState(false);
  const onMarketplaceAdded = useMarketplaceAdded();
  const marketplaceItems: DropdownMenuItem[] =
    upload === "plugin"
      ? [
          {
            kind: "action",
            id: "marketplace",
            icon: SvgGitHub,
            title: t("marketplace"),
            onSelect: () => setMarketplaceOpen(true),
          },
          {
            kind: "action",
            id: "manage-marketplaces",
            icon: SvgSettings,
            title: t("manageMarketplaces"),
            onSelect: () => navigation.go(MARKETPLACES_PATH),
          },
        ]
      : [];

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
              id: "upload",
              icon: SvgUploadCloud,
              title: upload === "plugin" ? t("uploadPlugin") : t("upload"),
              onSelect: () =>
                upload === "plugin"
                  ? setPluginUploadOpen(true)
                  : setUploadOpen(true),
            },
            {
              kind: "action",
              id: "create",
              icon: SvgEdit,
              title: t("create"),
              onSelect: () => navigation.go(newSkillHref()),
            },
            ...marketplaceItems,
          ]}
        />
      </Dropdown>
      <CreateSkillModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onImported={revalidate}
        onContinue={(draft) => {
          setUploadOpen(false);
          navigation.go(newSkillHref(stageSkillCreationDraft(draft)));
        }}
      />
      <UploadPluginFlow
        open={pluginUploadOpen}
        onClose={() => setPluginUploadOpen(false)}
      />
      <AddMarketplaceModal
        open={marketplaceOpen}
        onClose={() => setMarketplaceOpen(false)}
        onAdded={(marketplace) => {
          setMarketplaceOpen(false);
          onMarketplaceAdded(marketplace);
          navigation.go(MARKETPLACES_PATH);
        }}
      />
    </>
  );
}
