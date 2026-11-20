"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Dropdown, type DropdownMenuItem } from "@opal/components";
import { SvgEdit, SvgPlus, SvgSettings, SvgUploadCloud } from "@opal/icons";
import { SvgGitHub } from "@opal/logos";
import { useNavigation } from "@opal/navigation";
import { toast } from "@opal/layouts";
import {
  MARKETPLACES_PATH,
  newSkillHref,
  pluginHref,
} from "@/lib/customize/paths";
import { useMarketplaceAdded } from "@/lib/marketplaces/hooks";
import { stageSkillCreationDraft } from "@/lib/skills/creationDraft";
import { useRefreshSkillLists } from "@/lib/skills/hooks";
import CreateSkillModal from "@/sections/modals/skills/CreateSkillModal";
import AddMarketplaceModal from "@/sections/marketplaces/AddMarketplaceModal";
import UploadPluginModal from "@/sections/modals/plugins/UploadPluginModal";

interface AddSkillMenuProps {
  upload?: "skill" | "plugin";
}

export default function AddSkillMenu({ upload = "skill" }: AddSkillMenuProps) {
  const t = useTranslations("customize.skills.add");
  const uploadCopy = useTranslations("plugins.upload");
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
      <UploadPluginModal
        open={pluginUploadOpen}
        onClose={() => setPluginUploadOpen(false)}
        onContinueSkill={(draft) => {
          setPluginUploadOpen(false);
          navigation.go(newSkillHref(stageSkillCreationDraft(draft)));
        }}
        onSaved={(
          { target, plugin, unchanged, name_conflicts },
          needsAttention
        ) => {
          setPluginUploadOpen(false);
          revalidate();
          const values = {
            name: target.plugin_name,
            version: target.version_number,
          };
          if (unchanged) {
            toast.info(uploadCopy("saved.unchanged", values));
          } else if (name_conflicts.length > 0) {
            toast.warning(
              uploadCopy("saved.off", {
                ...values,
                names: name_conflicts.join(", "),
              })
            );
          } else {
            toast.success(
              target.kind === "new_version"
                ? uploadCopy("saved.newVersion", values)
                : uploadCopy("saved.newPlugin", values)
            );
          }
          navigation.go(
            pluginHref(plugin.id, needsAttention ? "integrations" : undefined)
          );
        }}
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
