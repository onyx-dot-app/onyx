"use client";

import { useRef, useState } from "react";
import { Button, MessageCard } from "@opal/components";
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
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";
import { SvgGlobe } from "@opal/icons";
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
  const { data, error, isLoading, refresh } = useAdminSkills();

  const [uploadOpen, setUploadOpen] = useState(false);
  const [shareTarget, setShareTarget] = useState<CustomSkill | null>(null);
  const [promoteTarget, setPromoteTarget] = useState<CustomSkill | null>(null);
  const [promoting, setPromoting] = useState(false);
  const replaceBundleTarget = useRef<CustomSkill | null>(null);
  const replaceFileRef = useRef<HTMLInputElement>(null);

  async function handleToggleEnabled(skill: CustomSkill) {
    try {
      await patchCustomSkill(skill.id, { enabled: !skill.enabled });
      toast.success(
        `${skill.enabled ? "Disabled" : "Re-enabled"} "${skill.name}"`
      );
      refresh();
    } catch (err) {
      console.error("Failed to update skill enabled state", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to update skill"
      );
    }
  }

  async function handlePromoteConfirmed() {
    const target = promoteTarget;
    if (!target || promoting) return;

    setPromoting(true);
    try {
      await patchCustomSkill(target.id, { is_public: true });
      toast.success(`Promoted "${target.name}" to the whole organization`);
      setPromoteTarget(null);
      refresh();
    } catch (err) {
      console.error("Failed to promote skill", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to promote skill"
      );
    } finally {
      setPromoting(false);
    }
  }

  async function handleDelete(skill: CustomSkill) {
    try {
      await deleteCustomSkill(skill.id);
      toast.success(`Deleted "${skill.name}"`);
      refresh();
    } catch (err) {
      console.error("Failed to delete skill", err);
      toast.error(err instanceof Error ? err.message : "Failed to delete");
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
      toast.success(`Replaced bundle for "${target.name}"`);
      refresh();
    } catch (err) {
      console.error("Failed to replace skill bundle", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to replace bundle"
      );
    }
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgBlocks}
        title="Skills"
        description="Capability bundles the Craft agent can reach for. Built-in skills ship with Onyx; custom skills are uploaded zip bundles, gated by group grants."
        rightChildren={
          onBack ? (
            <div className="flex items-center gap-2">
              <Button
                prominence="secondary"
                icon={SvgArrowLeft}
                onClick={onBack}
              >
                Back
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
            title="Failed to load skills"
            description="Check the console for details and try refreshing the page."
          />
        )}

        {!isLoading && !error && data && (
          <Section gap={2} alignItems="stretch">
            {/* Built-ins */}
            <Section gap={0.5} alignItems="stretch">
              <Text as="p" headingH3 text05>
                Built-in skills
              </Text>
              {data.builtins.length === 0 ? (
                <IllustrationContent
                  illustration={SvgNoResult}
                  title="No built-in skills registered"
                  description="Built-ins ship with the deploy."
                />
              ) : (
                <BuiltinSkillsTable skills={data.builtins} />
              )}
            </Section>

            {/* Customs */}
            <Section gap={0.5} alignItems="stretch">
              <div className="flex items-center justify-between gap-2">
                <Text as="p" headingH3 text05>
                  Custom skills
                </Text>
                <Button icon={SvgPlus} onClick={() => setUploadOpen(true)}>
                  Upload skill
                </Button>
              </div>
              <CustomSkillsTable
                skills={data.customs}
                onShareSkill={setShareTarget}
                onPromoteSkill={setPromoteTarget}
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

      {promoteTarget && (
        <ConfirmEntityModal
          icon={SvgGlobe}
          entityType="skill"
          entityName={promoteTarget.name}
          action="promote"
          actionButtonText="Promote"
          additionalDetails={`"${promoteTarget.name}" is a personal skill of ${
            promoteTarget.author_email ?? "its author"
          }. Promoting makes it available to everyone in the organization, and the author loses self-serve management of it.`}
          onClose={() => setPromoteTarget(null)}
          onSubmit={handlePromoteConfirmed}
        />
      )}
    </SettingsLayouts.Root>
  );
}
