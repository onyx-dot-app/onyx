"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Dropdown, type DropdownMenuItem } from "@opal/components";
import { SvgEdit, SvgPlus, SvgUploadCloud } from "@opal/icons";
import { SvgGitHub } from "@opal/logos";
import { useNavigation } from "@opal/navigation";
import { newSkillHref } from "@/lib/customize/paths";
import { stageSkillCreationDraft } from "@/lib/skills/creationDraft";
import { useRefreshPluginLists } from "@/lib/skills/hooks";
import CreateSkillModal from "@/sections/modals/skills/CreateSkillModal";

type AddSkillMenuProps =
  | { upload?: "skill" }
  | {
      upload: "plugin";
      onUploadPlugin: () => void;
      onAddMarketplace: () => void;
    };

export default function AddSkillMenu(props: AddSkillMenuProps) {
  const t = useTranslations("customize.skills.add");
  const navigation = useNavigation();
  const revalidate = useRefreshPluginLists();
  const [uploadOpen, setUploadOpen] = useState(false);
  // A plugin is uploaded or synced, not written here.
  const items: DropdownMenuItem[] =
    props.upload === "plugin"
      ? [
          {
            kind: "action",
            id: "upload",
            icon: SvgUploadCloud,
            title: t("uploadPlugin"),
            onSelect: props.onUploadPlugin,
          },
          {
            kind: "action",
            id: "marketplace",
            icon: SvgGitHub,
            title: t("marketplace"),
            onSelect: props.onAddMarketplace,
          },
        ]
      : [
          {
            kind: "action",
            id: "upload",
            icon: SvgUploadCloud,
            title: t("upload"),
            onSelect: () => setUploadOpen(true),
          },
          {
            kind: "action",
            id: "create",
            icon: SvgEdit,
            title: t("create"),
            onSelect: () => navigation.go(newSkillHref()),
          },
        ];

  return (
    <>
      <Dropdown align="end" width={60}>
        <Dropdown.Trigger asChild>
          <Button icon={SvgPlus}>{t("label")}</Button>
        </Dropdown.Trigger>
        <Dropdown.Data label={t("label")} items={items} />
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
    </>
  );
}
