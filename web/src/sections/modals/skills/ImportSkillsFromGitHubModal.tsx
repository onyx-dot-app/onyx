"use client";

import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Checkbox,
  InputTypeIn,
  MessageCard,
  Text,
} from "@opal/components";
import { Content, ContentAction, InputVertical, toast } from "@opal/layouts";
import { SvgGithub } from "@opal/logos";
import { importGitHubSkills, previewGitHubSkills } from "@/lib/skills/api";
import type { CustomSkill, GitHubSkillsPreview } from "@/lib/skills/types";
import Modal from "@/refresh-components/Modal";
import useUserExternalApps from "@/hooks/useUserExternalApps";
import { useUser } from "@/providers/UserProvider";
import { FetchError } from "@/lib/fetcher";
import type { ExternalAppUserResponse } from "@/app/craft/v1/apps/registry";

interface ImportSkillsFromGitHubModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: (skills: CustomSkill[]) => void;
}

interface ImportSkillsFromGitHubModalViewProps {
  open: boolean;
  onClose: () => void;
  repository: string;
  preview: GitHubSkillsPreview | null;
  selectedPaths: string[];
  loading: boolean;
  error: Error | null;
  isAdmin: boolean;
  externalApps: ExternalAppUserResponse[] | undefined;
  onRepositoryChange: (repository: string) => void;
  onResetPreview: () => void;
  onSelectedPathsChange: (paths: string[]) => void;
  onSubmit: () => void;
}

export default function ImportSkillsFromGitHubModal({
  open,
  onClose,
  onCreated,
}: ImportSkillsFromGitHubModalProps) {
  const [repository, setRepository] = useState("");
  const [preview, setPreview] = useState<GitHubSkillsPreview | null>(null);
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const { isAdmin } = useUser();
  const { data: externalApps } = useUserExternalApps();

  useEffect(() => {
    if (!open) {
      setRepository("");
      setPreview(null);
      setSelectedPaths([]);
      setError(null);
    }
  }, [open]);

  function handleClose() {
    if (!loading) onClose();
  }

  async function submit() {
    if (!repository.trim() || (preview && selectedPaths.length === 0)) return;
    setLoading(true);
    setError(null);
    try {
      if (!preview) {
        const result = await previewGitHubSkills(repository);
        setPreview(result);
        setSelectedPaths(
          result.skills
            .filter((skill) => skill.unavailable_reason === null)
            .map((skill) => skill.path)
        );
        return;
      }

      const created = await importGitHubSkills(
        preview.repository,
        preview.revision,
        preview.subpath,
        selectedPaths
      );
      toast.success(
        created.length === 1
          ? `Imported "${created[0]!.name}"`
          : `Imported ${created.length} skills`
      );
      onCreated(created);
      onClose();
    } catch (caught) {
      if (!(caught instanceof Error)) {
        console.error("Failed to import skills from GitHub:", caught);
      }
      setError(
        caught instanceof Error
          ? caught
          : new Error(
              preview ? "Couldn't import skills" : "Couldn't load repository"
            )
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <ImportSkillsFromGitHubModalView
      open={open}
      onClose={handleClose}
      repository={repository}
      preview={preview}
      selectedPaths={selectedPaths}
      loading={loading}
      error={error}
      isAdmin={isAdmin}
      externalApps={externalApps}
      onRepositoryChange={(nextRepository) => {
        setRepository(nextRepository);
        setPreview(null);
        setSelectedPaths([]);
        setError(null);
      }}
      onResetPreview={() => {
        setPreview(null);
        setSelectedPaths([]);
        setError(null);
      }}
      onSelectedPathsChange={setSelectedPaths}
      onSubmit={() => void submit()}
    />
  );
}

export function ImportSkillsFromGitHubModalView({
  open,
  onClose,
  repository,
  preview,
  selectedPaths,
  loading,
  error,
  isAdmin,
  externalApps,
  onRepositoryChange,
  onResetPreview,
  onSelectedPathsChange,
  onSubmit,
}: ImportSkillsFromGitHubModalViewProps) {
  const githubApp = externalApps?.find((app) => app.app_type === "GITHUB");
  const privateRepositoryAction = githubApp?.authenticated
    ? null
    : githubApp
      ? {
          label: "Connect GitHub for private repositories",
          href: "/craft/v1/apps?connect=github" as const,
        }
      : externalApps && isAdmin
        ? {
            label: "Set up private repository access",
            href: "/admin/craft/apps" as const,
          }
        : null;
  const errorCode =
    error instanceof FetchError &&
    error.info &&
    typeof error.info === "object" &&
    typeof error.info.error_code === "string"
      ? error.info.error_code
      : null;
  const retryableError = [
    "BAD_GATEWAY",
    "GATEWAY_TIMEOUT",
    "RATE_LIMITED",
    "SERVICE_UNAVAILABLE",
  ].includes(errorCode ?? "");
  const githubErrorAction = [
    "INSUFFICIENT_PERMISSIONS",
    "UNAUTHENTICATED",
  ].includes(errorCode ?? "")
    ? githubApp
      ? {
          label:
            errorCode === "UNAUTHENTICATED"
              ? "Reconnect GitHub"
              : "Manage GitHub",
          href: "/craft/v1/apps?connect=github" as const,
        }
      : externalApps && isAdmin
        ? {
            label: "Set up GitHub",
            href: "/admin/craft/apps" as const,
          }
        : null
    : null;
  const importablePaths =
    preview?.skills
      .filter((skill) => skill.unavailable_reason === null)
      .map((skill) => skill.path) ?? [];
  const allImportableSelected =
    importablePaths.length > 0 &&
    importablePaths.every((path) => selectedPaths.includes(path));
  const unavailableCount = preview
    ? preview.skills.length - importablePaths.length
    : 0;
  const previewSource = preview?.subpath
    ? `${preview.repository}/${preview.subpath}`
    : preview?.repository;
  const selectionSummary = [
    `${selectedPaths.length} selected`,
    unavailableCount > 0 ? `${unavailableCount} unavailable` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <Modal open={open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
      <Modal.Content width="md" height="lg">
        <Modal.Header
          icon={SvgGithub}
          title="Import from GitHub"
          description={
            preview
              ? "Choose the skills you want to import."
              : "Paste a repository URL to find skills you can import."
          }
          onClose={onClose}
        />
        <Modal.Body>
          {!preview ? (
            <>
              <InputVertical
                title="Repository"
                withLabel="github-repository"
                description="Paste a GitHub URL or enter owner/repository."
              >
                <InputTypeIn
                  id="github-repository"
                  value={repository}
                  placeholder="https://github.com/owner/repository"
                  variant={loading ? "disabled" : "primary"}
                  onChange={(event) => onRepositoryChange(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      onSubmit();
                    }
                  }}
                />
              </InputVertical>

              {privateRepositoryAction ? (
                <Button
                  href={privateRepositoryAction.href}
                  variant="action"
                  prominence="tertiary"
                  size="sm"
                >
                  {privateRepositoryAction.label}
                </Button>
              ) : externalApps && !githubApp ? (
                <Text as="p" font="secondary-body" color="text-03">
                  Private repositories require GitHub access configured by a
                  workspace admin.
                </Text>
              ) : null}
            </>
          ) : (
            <ContentAction
              title={previewSource ?? preview.repository}
              description="GitHub repository"
              sizePreset="main-ui"
              variant="section"
              padding="fit"
              center
              rightChildren={
                <Button
                  prominence="tertiary"
                  size="sm"
                  disabled={loading}
                  onClick={onResetPreview}
                >
                  Change
                </Button>
              }
            />
          )}

          {error && (
            <MessageCard
              variant="error"
              title={
                preview ? "Couldn’t import skills" : "Couldn’t load repository"
              }
              description={error.message}
              titleMaxLines={undefined}
              rightChildren={
                retryableError ? (
                  <Button
                    prominence="secondary"
                    size="sm"
                    disabled={loading}
                    onClick={onSubmit}
                  >
                    Retry
                  </Button>
                ) : githubErrorAction ? (
                  <Button
                    href={githubErrorAction.href}
                    prominence="secondary"
                    size="sm"
                  >
                    {githubErrorAction.label}
                  </Button>
                ) : undefined
              }
            />
          )}

          {preview && (
            <div className="flex w-full flex-col gap-2">
              <ContentAction
                title={`${preview.skills.length} ${preview.skills.length === 1 ? "skill" : "skills"} found`}
                description={
                  importablePaths.length === 0
                    ? "None are available to import."
                    : selectionSummary
                }
                sizePreset="main-content"
                variant="section"
                padding="fit"
                center
                rightChildren={
                  importablePaths.length > 1 ? (
                    <Button
                      prominence="tertiary"
                      size="sm"
                      disabled={loading}
                      onClick={() =>
                        onSelectedPathsChange(
                          allImportableSelected ? [] : importablePaths
                        )
                      }
                    >
                      {allImportableSelected ? "Clear all" : "Select all"}
                    </Button>
                  ) : undefined
                }
              />
              <Card border="solid" padding="fit" rounding="sm">
                <div className="divide-y divide-border-01">
                  {preview.skills.map((skill) => {
                    const checked = selectedPaths.includes(skill.path);
                    const unavailable = skill.unavailable_reason !== null;
                    return (
                      <label
                        key={skill.path}
                        aria-disabled={unavailable}
                        className={`flex w-full items-start gap-3 p-3 ${unavailable ? "cursor-not-allowed" : "cursor-pointer"}`}
                      >
                        <Checkbox
                          checked={checked}
                          disabled={loading || unavailable}
                          aria-label={`Select ${skill.name}`}
                          onCheckedChange={(nextChecked) =>
                            onSelectedPathsChange(
                              nextChecked
                                ? [...selectedPaths, skill.path]
                                : selectedPaths.filter(
                                    (path) => path !== skill.path
                                  )
                            )
                          }
                        />
                        <Content
                          title={skill.name}
                          description={
                            skill.unavailable_reason ?? skill.description
                          }
                          titleMaxLines={1}
                          descriptionMaxLines={2}
                          sizePreset="main-ui"
                          variant="section"
                          color={unavailable ? "muted" : "default"}
                        />
                      </label>
                    );
                  })}
                </div>
              </Card>
            </div>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" disabled={loading} onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={
              loading ||
              !repository.trim() ||
              (preview !== null && selectedPaths.length === 0)
            }
            onClick={onSubmit}
          >
            {loading
              ? preview
                ? "Importing…"
                : "Finding skills…"
              : preview
                ? selectedPaths.length === 0
                  ? importablePaths.length === 0
                    ? "No skills available"
                    : "Select skills"
                  : `Import ${selectedPaths.length === 1 ? "skill" : `${selectedPaths.length} skills`}`
                : "Find skills"}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
