"use client";

import { useMemo, useState } from "react";
import { Button, Tag } from "@opal/components";
import { SvgBlocks, SvgPlus } from "@opal/icons";
import * as AppLayouts from "@/layouts/app-layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import CustomSkillsTable from "@/refresh-pages/admin/SkillsPage/CustomSkillsTable";
import UploadSkillModal from "@/refresh-pages/admin/SkillsPage/UploadSkillModal";
import ShareSkillModal from "@/refresh-pages/admin/SkillsPage/ShareSkillModal";
import InspectSkillModal from "@/refresh-pages/admin/SkillsPage/InspectSkillModal";
import {
  MOCK_BUILTIN_SKILLS,
  MOCK_CUSTOM_SKILLS,
  MOCK_CURRENT_USER,
  skillsOwnedBy,
  skillsSharedWith,
} from "@/refresh-pages/admin/SkillsPage/mockData";
import type {
  CustomSkill,
  SkillVisibility,
} from "@/refresh-pages/admin/SkillsPage/interfaces";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function UserSkillsPage() {
  // Local copy of skills so wireframe edits show up immediately.
  const [allSkills, setAllSkills] = useState<CustomSkill[]>(MOCK_CUSTOM_SKILLS);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [shareTarget, setShareTarget] = useState<CustomSkill | null>(null);
  const [inspectTarget, setInspectTarget] = useState<CustomSkill | null>(null);

  const owned = useMemo(
    () => allSkills.filter((s) => s.author.id === MOCK_CURRENT_USER.id),
    [allSkills]
  );
  const sharedWithMe = useMemo(
    () =>
      allSkills.filter(
        (s) =>
          s.author.id !== MOCK_CURRENT_USER.id &&
          s.enabled &&
          (s.visibility === "org_wide" ||
            s.visibility === "groups" ||
            s.visibility === "users_and_groups" ||
            s.visibility === "users")
      ),
    [allSkills]
  );

  const totalCount =
    MOCK_BUILTIN_SKILLS.filter((s) => s.available).length +
    owned.length +
    sharedWithMe.length;

  function patchSkill(
    skillId: string,
    patcher: (skill: CustomSkill) => CustomSkill
  ) {
    setAllSkills((prev) =>
      prev.map((s) => (s.id === skillId ? patcher(s) : s))
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
      author: MOCK_CURRENT_USER,
      visibility:
        input.visibility === "org_wide" ? "private" : input.visibility,
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
    setAllSkills((prev) => [newSkill, ...prev]);
  }

  function handleShareSave(visibility: SkillVisibility) {
    if (!shareTarget) return;
    if (visibility === "org_wide") {
      // Non-admins can't directly set org_wide — keep the prior visibility.
      toast.info(
        "Org-wide is admin-only. Use Request org-wide to flag for promotion."
      );
      return;
    }
    patchSkill(shareTarget.id, (skill) => ({ ...skill, visibility }));
    toast.success(`Updated "${shareTarget.name}" sharing`);
  }

  function handleRequestOrgWide() {
    if (!shareTarget) return;
    patchSkill(shareTarget.id, (skill) => ({
      ...skill,
      promotion_requested: true,
    }));
    toast.success(`Requested org-wide promotion for "${shareTarget.name}"`);
  }

  function handleToggleEnabled(skill: CustomSkill) {
    patchSkill(skill.id, (s) => ({ ...s, enabled: !s.enabled }));
    toast.success(
      `${skill.enabled ? "Disabled" : "Re-enabled"} "${skill.name}"`
    );
  }

  function handleDelete(skill: CustomSkill) {
    setAllSkills((prev) => prev.filter((s) => s.id !== skill.id));
    toast.success(`Deleted "${skill.name}"`);
  }

  return (
    <AppLayouts.Root>
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          icon={SvgBlocks}
          title="Skills"
          description={`Capability bundles your Craft agent can reach for. You currently have ${totalCount} ${
            totalCount === 1 ? "skill" : "skills"
          } available across built-in, shared, and personal sources.`}
          rightChildren={
            <Button icon={SvgPlus} onClick={() => setUploadOpen(true)}>
              Upload skill
            </Button>
          }
        />
        <SettingsLayouts.Body>
          <Section gap={2} alignItems="stretch">
            {/* My skills */}
            <Section gap={0.5} alignItems="stretch">
              <Section gap={0.25} alignItems="start">
                <Text as="p" headingH3 text05>
                  Your skills
                </Text>
                <Text as="span" mainUiBody text03>
                  Skills you authored. Private by default — share with specific
                  users, with groups you belong to, or request admin promotion
                  to org-wide.
                </Text>
              </Section>
              {owned.length === 0 ? (
                <div className="rounded-md border border-dashed border-border-02 p-6 bg-background-tint-01">
                  <Section gap={0.5} alignItems="center">
                    <Text as="span" mainUiAction text05>
                      You haven&apos;t uploaded any skills yet.
                    </Text>
                    <Text as="span" mainUiBody text03>
                      Build a zip bundle with `SKILL.md` at the root and click{" "}
                      <strong>Upload skill</strong>.
                    </Text>
                  </Section>
                </div>
              ) : (
                <CustomSkillsTable
                  skills={owned}
                  adminMode={false}
                  showAuthor={false}
                  onOpenSkill={setInspectTarget}
                  onShareSkill={setShareTarget}
                  onReplaceBundle={(skill) =>
                    toast.info(
                      `Replace bundle for "${skill.name}" (wireframe — would open a file picker)`
                    )
                  }
                  onToggleEnabled={handleToggleEnabled}
                  onDeleteSkill={handleDelete}
                />
              )}
            </Section>

            {/* Shared with me */}
            <Section gap={0.5} alignItems="stretch">
              <Section gap={0.25} alignItems="start">
                <Text as="p" headingH3 text05>
                  Shared with you
                </Text>
                <Text as="span" mainUiBody text03>
                  Skills others have shared, including org-wide skills.
                  Read-only — if you want to modify one, download the zip and
                  upload your own version.
                </Text>
              </Section>
              {sharedWithMe.length === 0 ? (
                <div className="rounded-md border border-dashed border-border-02 p-6 bg-background-tint-01">
                  <Text as="span" mainUiBody text03>
                    Nothing shared with you yet.
                  </Text>
                </div>
              ) : (
                <CustomSkillsTable
                  skills={sharedWithMe}
                  adminMode={false}
                  showAuthor
                  onOpenSkill={setInspectTarget}
                />
              )}
            </Section>

            {/* Built-ins (read-only summary) */}
            <Section gap={0.5} alignItems="stretch">
              <Section gap={0.25} alignItems="start">
                <Text as="p" headingH3 text05>
                  Built-in skills
                </Text>
                <Text as="span" mainUiBody text03>
                  Ship with Onyx. Available whenever their dependencies are
                  configured.
                </Text>
              </Section>
              <Section gap={0.25} alignItems="stretch">
                {MOCK_BUILTIN_SKILLS.map((skill) => (
                  <div
                    key={skill.slug}
                    className="flex items-center justify-between gap-3 p-3 rounded-md border border-border-02 bg-background-neutral-00"
                  >
                    <Section gap={0.25} alignItems="start">
                      <Text as="span" mainUiAction text05>
                        {skill.name}
                      </Text>
                      <Text as="span" mainUiBody text03>
                        {skill.description}
                      </Text>
                    </Section>
                    {skill.available ? (
                      <Tag title="Available" color="green" />
                    ) : (
                      <div className="flex flex-col items-end gap-0.5">
                        <Tag title="Unavailable" color="amber" />
                        {skill.unavailable_reason && (
                          <Text as="span" secondaryBody text03>
                            {skill.unavailable_reason}
                          </Text>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </Section>
            </Section>
          </Section>
        </SettingsLayouts.Body>

        <UploadSkillModal
          open={uploadOpen}
          onClose={() => setUploadOpen(false)}
          canSetOrgWide={false}
          onUpload={handleUpload}
        />

        <ShareSkillModal
          skill={shareTarget}
          open={shareTarget !== null}
          onClose={() => setShareTarget(null)}
          canSetOrgWide={false}
          onSave={handleShareSave}
          onRequestOrgWide={handleRequestOrgWide}
        />

        <InspectSkillModal
          skill={inspectTarget}
          open={inspectTarget !== null}
          onClose={() => setInspectTarget(null)}
          onReplaceBundle={
            inspectTarget?.author.id === MOCK_CURRENT_USER.id
              ? () =>
                  toast.info(
                    "Replace bundle (wireframe — would open file picker)"
                  )
              : undefined
          }
          onDownload={() => toast.info("Download zip (wireframe)")}
        />
      </SettingsLayouts.Root>
    </AppLayouts.Root>
  );
}
