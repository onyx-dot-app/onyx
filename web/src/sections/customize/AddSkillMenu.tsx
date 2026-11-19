"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Dropdown, useCreateModal } from "@opal/components";
import { SvgEdit, SvgPlus, SvgUploadCloud } from "@opal/icons";
import { SvgGitHub } from "@opal/logos";
import { useNavigation } from "@opal/navigation";
import { toast } from "@opal/layouts";
import { newSkillHref, pluginHref } from "@/lib/customize/paths";
import { stageSkillCreationDraft } from "@/lib/skills/creationDraft";
import { useRefreshSkillLists } from "@/lib/skills/hooks";
import CreateSkillModal from "@/sections/modals/skills/CreateSkillModal";
import ImportSkillsFromGitHubModal from "@/sections/modals/skills/ImportSkillsFromGitHubModal";
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
  const githubModal = useCreateModal();

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
            {
              kind: "action",
              id: "github",
              icon: SvgGitHub,
              title: t("github"),
              onSelect: () => githubModal.toggle(true),
            },
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
        onSaved={({ target, plugin }, needsAttention) => {
          setPluginUploadOpen(false);
          revalidate();
          toast.success(
            target.kind === "new_version"
              ? uploadCopy("saved.newVersion", {
                  name: target.plugin_name,
                  version: target.version_number,
                })
              : uploadCopy("saved.newPlugin", { name: target.plugin_name })
          );
          navigation.go(
            pluginHref(plugin.id, needsAttention ? "integrations" : undefined)
          );
        }}
      />
      <githubModal.Provider>
        <ImportSkillsFromGitHubModal
          open
          onClose={() => githubModal.toggle(false)}
          onImported={revalidate}
        />
      </githubModal.Provider>
    </>
  );
}
