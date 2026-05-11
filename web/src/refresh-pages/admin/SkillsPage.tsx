"use client";

import { useMemo, useState } from "react";
import { Button } from "@opal/components";
import { SvgBlocks, SvgPlus } from "@opal/icons";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import BuiltinSkillsTable from "@/refresh-pages/admin/SkillsPage/BuiltinSkillsTable";
import CustomSkillsTable from "@/refresh-pages/admin/SkillsPage/CustomSkillsTable";
import UploadSkillModal from "@/refresh-pages/admin/SkillsPage/UploadSkillModal";
import ShareSkillModal from "@/refresh-pages/admin/SkillsPage/ShareSkillModal";
import InspectSkillModal from "@/refresh-pages/admin/SkillsPage/InspectSkillModal";
import {
  MOCK_BUILTIN_SKILLS,
  MOCK_CUSTOM_SKILLS,
} from "@/refresh-pages/admin/SkillsPage/mockData";
import type {
  CustomSkill,
  SkillVisibility,
} from "@/refresh-pages/admin/SkillsPage/interfaces";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SkillsPage() {
  const [customSkills, setCustomSkills] =
    useState<CustomSkill[]>(MOCK_CUSTOM_SKILLS);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [shareTarget, setShareTarget] = useState<CustomSkill | null>(null);
  const [inspectTarget, setInspectTarget] = useState<CustomSkill | null>(null);

  const flaggedCount = useMemo(
    () =>
      customSkills.filter(
        (skill) => skill.promotion_requested && !skill.promoted_by_admin
      ).length,
    [customSkills]
  );

  function patchSkill(
    skillId: string,
    patcher: (skill: CustomSkill) => CustomSkill
  ) {
    setCustomSkills((prev) =>
      prev.map((skill) => (skill.id === skillId ? patcher(skill) : skill))
    );
  }

  function handleUpload(input: {
    file: File | null;
    slug: string;
    name: string;
    description: string;
    visibility: SkillVisibility;
  }) {
    setUploadOpen(false);
    toast.success(`Uploaded "${input.name}" (wireframe — no backend)`);
    const newSkill: CustomSkill = {
      id: `skill-new-${Date.now()}`,
      slug: input.slug,
      name: input.name,
      description: input.description,
      author: {
        id: "user-admin",
        name: "Onyx Admin",
        email: "admin@onyx.app",
        is_admin: true,
      },
      visibility: input.visibility,
      shared_user_count: 0,
      shared_group_count: 0,
      enabled: true,
      promotion_requested: false,
      promoted_by_admin: false,
      bundle: {
        sha256: "0".repeat(64),
        total_bytes: input.file?.size ?? 0,
        files: [
          {
            path: "SKILL.md",
            size_bytes: 1_024,
            executable: false,
            kind: "markdown",
          },
        ],
      },
      updated_at: new Date().toISOString(),
    };
    setCustomSkills((prev) => [newSkill, ...prev]);
  }

  function handleShareSave(visibility: SkillVisibility) {
    if (!shareTarget) return;
    patchSkill(shareTarget.id, (skill) => ({
      ...skill,
      visibility,
      promoted_by_admin: visibility === "org_wide",
    }));
    toast.success(`Updated "${shareTarget.name}" visibility`);
  }

  function handlePromote(skill: CustomSkill) {
    patchSkill(skill.id, (s) => ({
      ...s,
      visibility: "org_wide",
      promoted_by_admin: true,
      promotion_requested: false,
    }));
    toast.success(`Promoted "${skill.name}" to org-wide`);
  }

  function handleDemote(skill: CustomSkill) {
    patchSkill(skill.id, (s) => ({
      ...s,
      visibility: "private",
      promoted_by_admin: false,
    }));
    toast.success(`Demoted "${skill.name}"`);
  }

  function handleToggleEnabled(skill: CustomSkill) {
    patchSkill(skill.id, (s) => ({ ...s, enabled: !s.enabled }));
    toast.success(
      `${skill.enabled ? "Disabled" : "Re-enabled"} "${skill.name}"`
    );
  }

  function handleDelete(skill: CustomSkill) {
    setCustomSkills((prev) => prev.filter((s) => s.id !== skill.id));
    toast.success(`Deleted "${skill.name}"`);
  }

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={SvgBlocks}
        title="Skills"
        description="Capability bundles the Craft agent can reach for. Built-in skills ship with Onyx; custom skills are uploaded zip bundles, gated by group / user grants."
        rightChildren={
          <Button icon={SvgPlus} onClick={() => setUploadOpen(true)}>
            Upload skill
          </Button>
        }
      />
      <SettingsLayouts.Body>
        <Section gap={2} alignItems="stretch">
          {/* Built-ins */}
          <Section gap={0.5} alignItems="stretch">
            <Section gap={0.25} alignItems="start">
              <Text as="p" headingH3 text05>
                Built-in skills
              </Text>
              <Text as="span" mainUiBody text03>
                Ship with the deploy. Available automatically when their
                dependencies are configured. Admins can&apos;t toggle these
                per-org — wiring up the dependency is the toggle.
              </Text>
            </Section>
            <BuiltinSkillsTable skills={MOCK_BUILTIN_SKILLS} />
          </Section>

          {/* Customs */}
          <Section gap={0.5} alignItems="stretch">
            <Section gap={0.25} alignItems="start">
              <div className="flex items-center gap-2">
                <Text as="p" headingH3 text05>
                  Custom skills
                </Text>
                {flaggedCount > 0 && (
                  <Text as="span" secondaryAction text03>
                    · {flaggedCount} pending org-wide{" "}
                    {flaggedCount === 1 ? "request" : "requests"}
                  </Text>
                )}
              </div>
              <Text as="span" mainUiBody text03>
                Uploaded by admins or by users from the personal skills page.
                Visibility, promotion, and lifecycle controls live here.
              </Text>
            </Section>
            <CustomSkillsTable
              skills={customSkills}
              adminMode
              showAuthor
              onOpenSkill={setInspectTarget}
              onShareSkill={setShareTarget}
              onReplaceBundle={(skill) =>
                toast.info(
                  `Replace bundle for "${skill.name}" (wireframe — would open a file picker)`
                )
              }
              onToggleEnabled={handleToggleEnabled}
              onDeleteSkill={handleDelete}
              onPromoteSkill={handlePromote}
              onDemoteSkill={handleDemote}
            />
          </Section>
        </Section>
      </SettingsLayouts.Body>

      <UploadSkillModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        canSetOrgWide
        onUpload={handleUpload}
      />

      <ShareSkillModal
        skill={shareTarget}
        open={shareTarget !== null}
        onClose={() => setShareTarget(null)}
        canSetOrgWide
        onSave={handleShareSave}
      />

      <InspectSkillModal
        skill={inspectTarget}
        open={inspectTarget !== null}
        onClose={() => setInspectTarget(null)}
        onReplaceBundle={() =>
          toast.info("Replace bundle (wireframe — would open file picker)")
        }
        onDownload={() => toast.info("Download zip (wireframe)")}
      />
    </SettingsLayouts.Root>
  );
}
