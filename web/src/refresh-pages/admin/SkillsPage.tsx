"use client";

import { useRef, useState } from "react";
import { Button, MessageCard } from "@opal/components";
import { useTranslation } from "react-i18next";
import { IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { SvgArrowLeft, SvgBlocks, SvgPlus, SvgSimpleLoader } from "@opal/icons";
import { SettingsLayouts } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import useAdminSkills from "@/hooks/useAdminSkills";
import BuiltinSkillsTable from "@/refresh-pages/admin/SkillsPage/BuiltinSkillsTable";
import CustomSkillsTable from "@/refresh-pages/admin/SkillsPage/CustomSkillsTable";
import UploadSkillModal from "@/refresh-pages/admin/SkillsPage/UploadSkillModal";
import ShareSkillModal from "@/refresh-pages/admin/SkillsPage/ShareSkillModal";
import {
  deleteCustomSkill,
  patchCustomSkill,
  replaceCustomSkillBundle,
} from "@/lib/skills/api";
import type { CustomSkill } from "@/refresh-pages/admin/SkillsPage/interfaces";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

interface SkillsPageProps {
  onBack?: () => void;
}

export default function SkillsPage({ onBack }: SkillsPageProps = {}) {
  const { t } = useTranslation();
  const { data, error, isLoading, refresh } = useAdminSkills();

  const [uploadOpen, setUploadOpen] = useState(false);
  const [shareTarget, setShareTarget] = useState<CustomSkill | null>(null);
  const replaceBundleTarget = useRef<CustomSkill | null>(null);
  const replaceFileRef = useRef<HTMLInputElement>(null);

  async function handleToggleEnabled(skill: CustomSkill) {
    try {
      await patchCustomSkill(skill.id, { enabled: !skill.enabled });
      toast.success(
        skill.enabled
          ? t("admin.skills.disabled_success", { name: skill.name })
          : t("admin.skills.enabled_success", { name: skill.name })
      );
      refresh();
    } catch (err) {
      console.error("Failed to update skill enabled state", err);
      toast.error(
        err instanceof Error
          ? err.message
          : t("admin.skills.toggle_failed", "Failed to update skill")
      );
    }
  }

  async function handleDelete(skill: CustomSkill) {
    try {
      await deleteCustomSkill(skill.id);
      toast.success(t("admin.skills.delete_success", { name: skill.name }));
      refresh();
    } catch (err) {
      console.error("Failed to delete skill", err);
      toast.error(
        err instanceof Error
          ? err.message
          : t("admin.skills.delete_failed", "Failed to delete")
      );
    }
  }

  function handleReplaceBundleClick(skill: CustomSkill) {
    replaceBundleTarget.current = skill;
    replaceFileRef.current?.click();
  }

  async function handleReplaceBundleFile(
    event: React.ChangeEvent<HTMLInputElement>
  ) {
    const target = replaceBundleTarget.current;
    const file = event.target.files?.[0];
    event.target.value = "";
    replaceBundleTarget.current = null;
    if (!target || !file) return;

    try {
      await replaceCustomSkillBundle(target.id, file);
      toast.success(t("admin.skills.replace_success", { name: target.name }));
      refresh();
    } catch (err) {
      console.error("Failed to replace skill bundle", err);
      toast.error(
        err instanceof Error
          ? err.message
          : t("admin.skills.replace_failed", "Failed to replace bundle")
      );
    }
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgBlocks}
        title={t("admin.skills.title", "Skills")}
        description={t("admin.skills.header_description", "Capability bundles the Craft agent can reach for. Built-in skills ship with Onyx; custom skills are uploaded zip bundles, gated by group grants.")}
        rightChildren={
          onBack ? (
            <div className="flex items-center gap-2">
              <Button
                prominence="secondary"
                icon={SvgArrowLeft}
                onClick={onBack}
              >
                {t("general.back", "Back")}
              </Button>
            </div>
          ) : undefined
        }
      />
      <SettingsLayouts.Body>
        {isLoading && <SvgSimpleLoader />}

        {error && !isLoading && (
          <MessageCard
            variant="error"
            title={t("admin.skills.load_failed", "Failed to load skills")}
            description={t("admin.skills.load_failed_desc", "Check the console for details and try refreshing the page.")}
          />
        )}

        {!isLoading && !error && data && (
          <Section gap={2} alignItems="stretch">
            {/* Built-ins */}
            <Section gap={0.5} alignItems="stretch">
              <Text as="p" headingH3 text05>
                {t("admin.skills.builtin_skills", "Built-in skills")}
              </Text>
              {data.builtins.length === 0 ? (
                <IllustrationContent
                  illustration={SvgNoResult}
                  title={t("admin.skills.no_builtin_skills", "No built-in skills registered")}
                  description={t("admin.skills.builtin_skills_desc", "Built-ins ship with the deploy.")}
                />
              ) : (
                <BuiltinSkillsTable skills={data.builtins} />
              )}
            </Section>

            {/* Customs */}
            <Section gap={0.5} alignItems="stretch">
              <div className="flex items-center justify-between gap-2">
                <Text as="p" headingH3 text05>
                  {t("admin.skills.custom_skills", "Custom skills")}
                </Text>
                <Button icon={SvgPlus} onClick={() => setUploadOpen(true)}>
                  {t("admin.skills.upload_skill", "Upload skill")}
                </Button>
              </div>
              <CustomSkillsTable
                skills={data.customs}
                onShareSkill={setShareTarget}
                onReplaceBundle={handleReplaceBundleClick}
                onToggleEnabled={handleToggleEnabled}
                onDeleteSkill={handleDelete}
              />
            </Section>
          </Section>
        )}
      </SettingsLayouts.Body>

      {/* Inline file picker for the row-level "Replace bundle" action so we
          don't have to open the Inspect modal first. */}
      <input
        ref={replaceFileRef}
        type="file"
        accept=".zip,application/zip"
        className="hidden"
        onChange={handleReplaceBundleFile}
      />

      <UploadSkillModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUploaded={refresh}
      />

      <ShareSkillModal
        skill={shareTarget}
        open={shareTarget !== null}
        onClose={() => setShareTarget(null)}
        onSaved={refresh}
      />
    </SettingsLayouts.Root>
  );
}
