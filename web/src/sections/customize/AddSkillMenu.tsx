"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Dropdown, useCreateModal } from "@opal/components";
import { SvgEdit, SvgPlus, SvgUploadCloud } from "@opal/icons";
import { SvgGitHub } from "@opal/logos";
import { useNavigation } from "@opal/navigation";
import { newSkillHref } from "@/lib/customize/paths";
import { stageSkillCreationDraft } from "@/lib/skills/creationDraft";
import { useRefreshSkillLists } from "@/lib/skills/hooks";
import CreateSkillModal from "@/sections/modals/skills/CreateSkillModal";
import ImportSkillsFromGitHubModal from "@/sections/modals/skills/ImportSkillsFromGitHubModal";

export default function AddSkillMenu() {
  const t = useTranslations("customize.skills.add");
  const navigation = useNavigation();
  const revalidate = useRefreshSkillLists();
  const [uploadOpen, setUploadOpen] = useState(false);
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
