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
import { Content, InputVertical, toast } from "@opal/layouts";
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
  onSelectedPathsChange,
  onSubmit,
}: ImportSkillsFromGitHubModalViewProps) {
  const githubApp = externalApps?.find((app) => app.app_type === "GITHUB");
  const privateRepositoryGuidance = githubApp?.authenticated
    ? {
        message:
          "You can import public repositories and any private repositories your GitHub account can access.",
        action: null,
      }
    : githubApp
      ? {
          message:
            "Public repositories don't require a GitHub connection. Connect GitHub to import private repositories.",
          action: {
            label: "Connect GitHub",
            href: "/craft/v1/apps?connect=github" as const,
          },
        }
      : externalApps && isAdmin
        ? {
            message:
              "Public repositories don't require a GitHub connection. Set up the GitHub App to import private repositories.",
            action: {
              label: "Set up GitHub",
              href: "/admin/craft/apps" as const,
            },
          }
        : {
            message: externalApps
              ? "Public repositories don't require a GitHub connection. Ask a workspace admin to set up the GitHub App to import private repositories."
              : "Public repositories don't require a GitHub connection. Private repositories require a GitHub connection.",
            action: null,
          };
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

  return (
    <Modal open={open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
      <Modal.Content width="md" height="lg">
        <Modal.Header
          icon={SvgGithub}
          title="Import skills from GitHub"
          description="Choose one or more skills from a GitHub repository."
          onClose={onClose}
        />
        <Modal.Body>
          <InputVertical
            title="GitHub repository"
            withLabel="github-repository"
            description="Enter a repository URL or owner/repository."
          >
            <InputTypeIn
              id="github-repository"
              value={repository}
              placeholder="https://github.com/owner/repository"
              variant={loading ? "disabled" : "primary"}
              onChange={(event) => onRepositoryChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") onSubmit();
              }}
            />
          </InputVertical>

          <div className="flex w-full items-center justify-between gap-3">
            <Text as="p" font="secondary-body" color="text-03">
              {privateRepositoryGuidance.message}
            </Text>
            {privateRepositoryGuidance.action && (
              <Button
                href={privateRepositoryGuidance.action.href}
                variant="default"
                prominence="secondary"
                size="sm"
              >
                {privateRepositoryGuidance.action.label}
              </Button>
            )}
          </div>

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
              <Content
                title={`${preview.skills.length} ${preview.skills.length === 1 ? "skill" : "skills"} found`}
                description={
                  preview.skills.every(
                    (skill) => skill.unavailable_reason !== null
                  )
                    ? `None of the skills found in ${preview.repository} can be imported.`
                    : `Select the skills to import from ${preview.repository}.`
                }
                sizePreset="main-content"
                variant="section"
              />
              <div className="flex w-full flex-col gap-1">
                {preview.skills.map((skill) => {
                  const checked = selectedPaths.includes(skill.path);
                  const unavailable = skill.unavailable_reason !== null;
                  return (
                    <div
                      key={skill.path}
                      className={unavailable ? "opacity-60" : undefined}
                    >
                      <Card border="solid" padding="sm">
                        <label
                          aria-disabled={unavailable}
                          className={`flex w-full items-start gap-3 ${unavailable ? "cursor-not-allowed" : "cursor-pointer"}`}
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
                          <div className="min-w-0 flex-1">
                            <Text as="p" font="main-ui-action" color="text-04">
                              {skill.name}
                            </Text>
                            <Text as="p" font="secondary-body" color="text-03">
                              {skill.description}
                            </Text>
                            <Text as="p" font="secondary-body" color="text-02">
                              {skill.path === "."
                                ? "Repository root"
                                : skill.path}
                            </Text>
                            {skill.unavailable_reason && (
                              <Text
                                as="p"
                                font="secondary-body"
                                color="text-03"
                              >
                                {skill.unavailable_reason}
                              </Text>
                            )}
                          </div>
                        </label>
                      </Card>
                    </div>
                  );
                })}
              </div>
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
                ? "Importing..."
                : "Searching..."
              : preview
                ? selectedPaths.length === 0
                  ? "Nothing to import"
                  : `Import ${selectedPaths.length === 1 ? "skill" : `${selectedPaths.length} skills`}`
                : "Search repository"}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
