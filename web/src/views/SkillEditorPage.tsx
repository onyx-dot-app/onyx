"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import useSWR, { useSWRConfig } from "swr";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import {
  Button,
  Card,
  CompactMarkdown,
  Divider,
  InputTypeIn,
  MessageCard,
  Switch,
  Tag,
  Tooltip,
} from "@opal/components";
import {
  SvgArrowLeft,
  SvgBlocks,
  SvgShare,
  SvgSimpleLoader,
  SvgTrash,
  SvgUploadCloud,
} from "@opal/icons";
import {
  Content,
  InputHorizontal,
  InputVertical,
  SettingsLayouts,
} from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  deleteUserSkill,
  patchUserSkill,
  replaceUserSkillBundle,
} from "@/lib/skills/api";
import type { CustomSkill, SkillEditableDetail } from "@/lib/skills/types";
import { toast } from "@/hooks/useToast";
import InstructionsDisplayModeToggle, {
  type InstructionsDisplayMode,
} from "@/sections/skills/InstructionsDisplayModeToggle";
import ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";

interface SkillEditorPageProps {
  skillId: string;
}

function getSharingStatus(skill: SkillEditableDetail): {
  title: string;
  description: string;
  color: "blue" | "gray" | "purple";
} {
  if (skill.public_permission !== null) {
    return {
      title: "Organization",
      description:
        skill.public_permission === "EDITOR"
          ? "Everyone in your organization can use and edit this skill."
          : "Everyone in your organization can use this skill.",
      color: "blue",
    };
  }

  const userCount = skill.user_shares.length;
  const groupCount = skill.group_shares.length;
  const shareCount = userCount + groupCount;
  if (shareCount > 0) {
    return {
      title: `${shareCount} ${shareCount === 1 ? "share" : "shares"}`,
      description: "Only selected users and groups can use this skill.",
      color: "gray",
    };
  }

  return {
    title: "Personal",
    description: "Only you can use this skill.",
    color: "purple",
  };
}

export default function SkillEditorPage({ skillId }: SkillEditorPageProps) {
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const replaceFileRef = useRef<HTMLInputElement>(null);
  const {
    data: skill,
    error,
    isLoading,
    mutate: refreshSkill,
  } = useSWR<SkillEditableDetail>(
    SWR_KEYS.editableSkill(skillId),
    errorHandlingFetcher
  );

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [instructionsMarkdown, setInstructionsMarkdown] = useState("");
  const [instructionsDisplayMode, setInstructionsDisplayMode] =
    useState<InstructionsDisplayMode>("raw");
  const [hydratedSkillId, setHydratedSkillId] = useState<string | null>(null);
  const [shareOpen, setShareOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isReplacingFiles, setIsReplacingFiles] = useState(false);
  const [isTogglingEnabled, setIsTogglingEnabled] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const syncEditableFields = useCallback((nextSkill: SkillEditableDetail) => {
    setName(nextSkill.name);
    setDescription(nextSkill.description);
    setInstructionsMarkdown(nextSkill.instructions_markdown);
  }, []);

  useEffect(() => {
    if (!skill || hydratedSkillId === skill.id) return;
    syncEditableFields(skill);
    setHydratedSkillId(skill.id);
  }, [hydratedSkillId, skill, syncEditableFields]);

  const isDirty = useMemo(() => {
    if (!skill) return false;
    return (
      name !== skill.name ||
      description !== skill.description ||
      instructionsMarkdown !== skill.instructions_markdown
    );
  }, [description, instructionsMarkdown, name, skill]);

  const canManageSkill =
    skill?.user_permission === "OWNER" || skill?.user_permission === "EDITOR";

  // A bundle upload rewrites name/description/instructions from SKILL.md, so
  // lock the detail fields while one is in flight: edits made mid-upload
  // would be clobbered by the post-upload sync (or race it via Save).
  const fieldsLocked = !canManageSkill || isReplacingFiles;

  const canSave =
    !!skill &&
    canManageSkill &&
    !isReplacingFiles &&
    isDirty &&
    !!name.trim() &&
    !!description.trim() &&
    !!instructionsMarkdown.trim() &&
    !isSaving;

  function navigateBack() {
    router.push("/craft/v1/skills" as Route);
  }

  async function refreshSkillList() {
    await mutate(SWR_KEYS.userSkills);
  }

  async function updateLocalSkill(updated: CustomSkill) {
    if (!skill) return;
    const nextSkill: SkillEditableDetail = { ...skill, ...updated };
    await refreshSkill(nextSkill, { revalidate: false });
    await refreshSkillList();
  }

  async function handleSave(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!skill || !canSave) return;
    setIsSaving(true);
    try {
      const updated = await patchUserSkill(skill.id, {
        name,
        description,
        instructions_markdown: instructionsMarkdown,
      });
      const refreshed = await refreshSkill();
      if (refreshed) {
        syncEditableFields(refreshed);
      } else {
        const nextSkill: SkillEditableDetail = {
          ...skill,
          ...updated,
          instructions_markdown: instructionsMarkdown.trim(),
        };
        await refreshSkill(nextSkill, { revalidate: false });
        syncEditableFields(nextSkill);
      }
      await refreshSkillList();
      toast.success(`Saved "${updated.name}"`);
    } catch (err) {
      console.error("Failed to save skill", err);
      toast.error(err instanceof Error ? err.message : "Failed to save skill");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleSharingSaved() {
    await refreshSkill();
    await refreshSkillList();
  }

  function handleReplaceFilesClick() {
    replaceFileRef.current?.click();
  }

  async function handleReplaceFiles(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!skill || !file || !canManageSkill || isDirty) return;

    setIsReplacingFiles(true);
    try {
      const updated = await replaceUserSkillBundle(skill.id, file);
      await refreshSkillList();
      const refreshed = await refreshSkill();
      if (refreshed) {
        syncEditableFields(refreshed);
      }
      toast.success(`Replaced files for "${updated.name}"`);
    } catch (err) {
      console.error("Failed to replace skill files", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to replace skill files"
      );
    } finally {
      setIsReplacingFiles(false);
    }
  }

  async function handleToggleEnabled(enabled: boolean) {
    if (!skill || !canManageSkill) return;

    setIsTogglingEnabled(true);
    try {
      const updated = await patchUserSkill(skill.id, { enabled });
      await updateLocalSkill(updated);
      toast.success(`${enabled ? "Enabled" : "Disabled"} "${updated.name}"`);
    } catch (err) {
      console.error("Failed to toggle skill", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to update skill"
      );
    } finally {
      setIsTogglingEnabled(false);
    }
  }

  async function handleDeleteConfirmed() {
    if (!skill || !canManageSkill || isDeleting) return;

    setIsDeleting(true);
    try {
      await deleteUserSkill(skill.id);
      // The skill is gone — a transient list-refresh failure must not mask
      // the successful delete or block navigation off the dead editor page.
      void refreshSkillList();
      toast.success(`Deleted "${skill.name}"`);
      router.push("/craft/v1/skills" as Route);
    } catch (err) {
      console.error("Failed to delete skill", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to delete skill"
      );
    } finally {
      setIsDeleting(false);
    }
  }

  const saveTooltip = isSaving
    ? "Saving changes..."
    : !skill
      ? undefined
      : !canManageSkill
        ? "You don't have permission to edit this skill's details."
        : !name.trim()
          ? "Add a title before saving."
          : !description.trim()
            ? "Add a description before saving."
            : !instructionsMarkdown.trim()
              ? "Add instructions before saving."
              : !isDirty
                ? "No changes have been made."
                : undefined;

  const sharingStatus = skill ? getSharingStatus(skill) : null;
  const replaceFilesDisabled =
    !canManageSkill || isReplacingFiles || isSaving || isDirty;
  const replaceFilesTooltip = isDirty
    ? "Save detail changes before replacing skill files."
    : isReplacingFiles
      ? "Replacing skill files..."
      : !canManageSkill
        ? "You don't have permission to replace this skill's files."
        : undefined;

  return (
    <form
      className="h-full w-full"
      data-testid="SkillEditorPage/container"
      onSubmit={handleSave}
    >
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={SvgBlocks}
          title="Edit skill"
          description={skill?.slug}
          rightChildren={
            <div className="flex items-center gap-2">
              <Button
                prominence="secondary"
                type="button"
                icon={SvgArrowLeft}
                onClick={navigateBack}
              >
                Cancel
              </Button>
              <Tooltip tooltip={saveTooltip} side="bottom">
                <Button disabled={!canSave} type="submit">
                  {isSaving ? "Saving..." : "Save"}
                </Button>
              </Tooltip>
            </div>
          }
          backButton
          divider
        />

        <SettingsLayouts.Body>
          {isLoading && (
            <div className="flex min-h-40 items-center justify-center">
              <SvgSimpleLoader />
            </div>
          )}

          {error && !isLoading && (
            <MessageCard
              variant="error"
              title="Skill unavailable"
              description="This skill may not exist, may be built-in, or may not be editable by your account."
            />
          )}

          {skill && !isLoading && !error && (
            <>
              <Section alignItems="stretch">
                <InputVertical withLabel="name" title="Name">
                  <InputTypeIn
                    id="name"
                    name="name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="Name your skill"
                    variant={fieldsLocked ? "disabled" : "primary"}
                  />
                </InputVertical>

                <InputVertical
                  withLabel="description"
                  title="Description"
                  description="Describe when this skill should be used."
                >
                  <InputTextArea
                    id="description"
                    name="description"
                    rows={4}
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="What does this skill help with?"
                    autoResize
                    maxRows={8}
                    variant={fieldsLocked ? "disabled" : "primary"}
                  />
                </InputVertical>
              </Section>

              <Divider paddingParallel="fit" paddingPerpendicular="fit" />

              <Section alignItems="stretch">
                <div className="flex w-full items-start justify-between gap-2">
                  <Content
                    title="Instructions"
                    description="Write the behavior and workflow this skill adds to Craft."
                    sizePreset="main-content"
                    variant="section"
                  />
                  <InstructionsDisplayModeToggle
                    value={instructionsDisplayMode}
                    onChange={setInstructionsDisplayMode}
                  />
                </div>

                <Card border="solid" rounding="lg" padding="sm">
                  {instructionsDisplayMode === "raw" ? (
                    <InputTextArea
                      id="instructions_markdown"
                      name="instructions_markdown"
                      rows={22}
                      value={instructionsMarkdown}
                      onChange={(event) =>
                        setInstructionsMarkdown(event.target.value)
                      }
                      className="min-h-[34rem] border-0"
                      placeholder="Write the skill instructions."
                      variant={fieldsLocked ? "disabled" : "internal"}
                    />
                  ) : (
                    <div className="min-h-[34rem] max-h-[70dvh] overflow-y-auto overflow-x-hidden rounded-08 bg-background-neutral-00 p-2">
                      <CompactMarkdown>
                        {instructionsMarkdown || "No instructions yet."}
                      </CompactMarkdown>
                    </div>
                  )}
                </Card>
              </Section>

              <Divider paddingParallel="fit" paddingPerpendicular="fit" />

              <Section gap={0.5} alignItems="stretch" height="auto">
                <Content
                  title="Management"
                  description="Control who can use this skill and whether Craft can currently select it."
                  sizePreset="main-content"
                  variant="section"
                />
                <Card border="solid" rounding="lg">
                  <Section>
                    {sharingStatus && (
                      <InputHorizontal
                        title="Sharing"
                        description={sharingStatus.description}
                        center
                      >
                        <div className="flex items-center gap-2">
                          <Tag
                            title={sharingStatus.title}
                            color={sharingStatus.color}
                          />
                          {canManageSkill && (
                            <Button
                              type="button"
                              prominence="secondary"
                              icon={SvgShare}
                              onClick={() => setShareOpen(true)}
                            >
                              Edit sharing
                            </Button>
                          )}
                        </div>
                      </InputHorizontal>
                    )}

                    {canManageSkill && (
                      <InputHorizontal
                        title="Skill files"
                        description="Replace the ZIP bundle for this skill. The slug stays the same; name, description, and instructions are read from the new SKILL.md."
                        center
                      >
                        <Tooltip tooltip={replaceFilesTooltip} side="bottom">
                          <Button
                            type="button"
                            prominence="secondary"
                            icon={SvgUploadCloud}
                            disabled={replaceFilesDisabled}
                            onClick={handleReplaceFilesClick}
                          >
                            {isReplacingFiles
                              ? "Replacing..."
                              : "Replace files"}
                          </Button>
                        </Tooltip>
                      </InputHorizontal>
                    )}

                    {canManageSkill && (
                      <InputHorizontal
                        title={skill.enabled ? "Enabled" : "Disabled"}
                        description={
                          skill.enabled
                            ? "Craft can use this skill when it is relevant."
                            : "Craft will not use this skill until it is re-enabled."
                        }
                        center
                      >
                        <Switch
                          checked={skill.enabled}
                          disabled={isTogglingEnabled}
                          onCheckedChange={handleToggleEnabled}
                        />
                      </InputHorizontal>
                    )}
                  </Section>
                </Card>
              </Section>

              {canManageSkill && (
                <>
                  <Divider paddingParallel="fit" paddingPerpendicular="fit" />

                  <Card border="solid" rounding="lg">
                    <Section>
                      <InputHorizontal
                        title="Delete this skill"
                        description="Anyone using this skill will lose access. Deletion cannot be undone."
                        center
                      >
                        <Button
                          type="button"
                          variant="danger"
                          prominence="secondary"
                          icon={SvgTrash}
                          disabled={isDeleting}
                          onClick={() => setDeleteOpen(true)}
                        >
                          Delete skill
                        </Button>
                      </InputHorizontal>
                    </Section>
                  </Card>
                </>
              )}
            </>
          )}
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      <input
        ref={replaceFileRef}
        type="file"
        accept=".zip,application/zip,application/x-zip-compressed"
        className="hidden"
        onChange={handleReplaceFiles}
      />

      <ShareSkillModal
        skill={shareOpen ? (skill ?? null) : null}
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        onSaved={handleSharingSaved}
      />

      {skill && deleteOpen && (
        <ConfirmEntityModal
          danger
          entityType="skill"
          entityName={skill.name}
          actionButtonText={isDeleting ? "Deleting..." : "Delete"}
          onClose={() => setDeleteOpen(false)}
          onSubmit={handleDeleteConfirmed}
        />
      )}
    </form>
  );
}
