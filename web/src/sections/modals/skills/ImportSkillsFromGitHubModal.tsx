"use client";

import { useEffect, useMemo, useState } from "react";
import type { Route } from "next";
import {
  Button,
  Card,
  Checkbox,
  InputTypeIn,
  MessageCard,
  Modal,
  Tag,
  Text,
} from "@opal/components";
import { SvgArrowRight } from "@opal/icons";
import { SvgGithub } from "@opal/logos";
import { cn } from "@opal/utils";
import useUserExternalApps from "@/hooks/useUserExternalApps";
import { useUser } from "@/providers/UserProvider";
import { importGitHubSkills, previewGitHubSkills } from "@/lib/skills/api";
import type {
  GitHubSkillNotImported,
  GitHubSkillsImportResult,
  GitHubSkillsPreview,
} from "@/lib/skills/types";
import type { ExternalAppUserResponse } from "@/app/craft/v1/apps/registry";

interface ImportSkillsFromGitHubModalProps {
  open: boolean;
  onClose: () => void;
  onImported: () => void;
}

interface ImportSkillsFromGitHubModalViewProps {
  open: boolean;
  repository: string;
  preview: GitHubSkillsPreview | null;
  selectedPaths: string[];
  result: GitHubSkillsImportResult | null;
  loading: boolean;
  error: string | null;
  isAdmin: boolean;
  externalApps: ExternalAppUserResponse[] | undefined;
  onClose: () => void;
  onRepositoryChange: (value: string) => void;
  onSelectedPathsChange: (paths: string[]) => void;
  onSubmit: () => void;
}

export default function ImportSkillsFromGitHubModal({
  open,
  onClose,
  onImported,
}: ImportSkillsFromGitHubModalProps) {
  const [repository, setRepository] = useState("");
  const [preview, setPreview] = useState<GitHubSkillsPreview | null>(null);
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
  const [result, setResult] = useState<GitHubSkillsImportResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { isAdmin } = useUser();
  const { data: externalApps } = useUserExternalApps();

  useEffect(() => {
    if (open) return;
    setRepository("");
    setPreview(null);
    setSelectedPaths([]);
    setResult(null);
    setError(null);
  }, [open]);

  async function submit() {
    if (loading || !repository.trim()) return;
    setLoading(true);
    setError(null);
    try {
      if (!preview) {
        const nextPreview = await previewGitHubSkills(repository);
        setPreview(nextPreview);
        setSelectedPaths(
          nextPreview.skills
            .filter((skill) => skill.unavailable_reason === null)
            .map((skill) => skill.path)
        );
        return;
      }
      if (selectedPaths.length === 0) return;
      const nextResult = await importGitHubSkills(preview, selectedPaths);
      setResult(nextResult);
      if (nextResult.imported.length > 0) onImported();
    } catch (caught) {
      console.error("Failed to import skills from GitHub", caught);
      setError(
        caught instanceof Error
          ? caught.message
          : preview
            ? "Couldn't import skills."
            : "Couldn't load repository."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <ImportSkillsFromGitHubModalView
      open={open}
      repository={repository}
      preview={preview}
      selectedPaths={selectedPaths}
      result={result}
      loading={loading}
      error={error}
      isAdmin={isAdmin}
      externalApps={externalApps}
      onClose={onClose}
      onRepositoryChange={(value) => {
        setRepository(value);
        setPreview(null);
        setSelectedPaths([]);
        setResult(null);
        setError(null);
      }}
      onSelectedPathsChange={setSelectedPaths}
      onSubmit={() => void submit()}
    />
  );
}

export function ImportSkillsFromGitHubModalView({
  open,
  repository,
  preview,
  selectedPaths,
  result,
  loading,
  error,
  isAdmin,
  externalApps,
  onClose,
  onRepositoryChange,
  onSelectedPathsChange,
  onSubmit,
}: ImportSkillsFromGitHubModalViewProps) {
  const importablePaths = useMemo(
    () =>
      preview?.skills
        .filter((skill) => skill.unavailable_reason === null)
        .map((skill) => skill.path) ?? [],
    [preview]
  );
  const selectedPathSet = useMemo(
    () => new Set(selectedPaths),
    [selectedPaths]
  );
  const allImportableSelected =
    importablePaths.length > 0 &&
    importablePaths.every((path) => selectedPathSet.has(path));
  const githubApp = externalApps?.find((app) => app.app_type === "GITHUB");
  let privateRepositoryMessage =
    "Public repositories import directly. Private repositories require a GitHub connection.";
  let privateRepositoryAction: { label: string; href: Route } | null = null;
  if (githubApp?.authenticated) {
    privateRepositoryMessage =
      "Public repositories import directly. Private repositories use your GitHub connection.";
  } else if (githubApp) {
    privateRepositoryMessage =
      "Public repositories import directly. Connect GitHub to import private repositories.";
    privateRepositoryAction = {
      label: "Connect GitHub",
      href: "/craft/v1/apps",
    };
  } else if (externalApps && isAdmin) {
    privateRepositoryMessage =
      "Public repositories import directly. Set up GitHub before importing private repositories.";
    privateRepositoryAction = {
      label: "Set up GitHub",
      href: "/admin/craft/apps",
    };
  } else if (externalApps) {
    privateRepositoryMessage =
      "Public repositories import directly. Ask an admin to set up GitHub before importing private repositories.";
  }

  const previewUnavailable =
    preview?.skills
      .filter((skill) => skill.unavailable_reason !== null)
      .map<GitHubSkillNotImported>((skill) => ({
        path: skill.path,
        name: skill.name,
        reason: skill.unavailable_reason ?? "This skill cannot be imported.",
      })) ?? [];
  const previewUnavailablePaths = new Set(
    previewUnavailable.map((item) => item.path)
  );
  const resultNotImported = result
    ? [
        ...previewUnavailable,
        ...result.not_imported.filter(
          (item) => !previewUnavailablePaths.has(item.path)
        ),
      ]
    : [];
  const enabledCount =
    result?.imported.filter((item) => item.skill.enabled).length ?? 0;
  const disabledCount = (result?.imported.length ?? 0) - enabledCount;
  const notSelectedCount = result
    ? importablePaths.filter((path) => !selectedPathSet.has(path)).length
    : 0;

  return (
    <Modal open={open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
      <Modal.Content
        width={preview || result ? "md" : "sm"}
        height={preview || result ? "lg" : "fit"}
      >
        <Modal.Header
          icon={SvgGithub}
          title={result ? "GitHub import complete" : "Import from GitHub"}
          description={
            result
              ? "Review what was added to your skills."
              : preview
                ? `Choose skills from ${preview.repository}.`
                : "Import one or more skills from a GitHub repository."
          }
          onClose={loading ? undefined : onClose}
        />
        <Modal.Body>
          {result ? (
            <div className="flex w-full flex-col gap-3">
              <MessageCard
                variant={
                  result.imported.length === 0
                    ? "error"
                    : resultNotImported.length > 0 || disabledCount > 0
                      ? "warning"
                      : "success"
                }
                title={
                  result.imported.length === 0
                    ? "No skills were imported"
                    : `${result.imported.length} ${result.imported.length === 1 ? "skill" : "skills"} imported`
                }
                description={[
                  enabledCount > 0
                    ? `${enabledCount} enabled automatically.`
                    : null,
                  disabledCount > 0
                    ? `${disabledCount} imported disabled because another skill with the same name is enabled.`
                    : null,
                  resultNotImported.length > 0
                    ? `${resultNotImported.length} could not be imported.`
                    : null,
                  notSelectedCount > 0
                    ? `${notSelectedCount} not selected.`
                    : null,
                ]
                  .filter(Boolean)
                  .join(" ")}
              />

              {result.imported.length > 0 && (
                <section className="flex flex-col gap-1.5">
                  <Text font="main-ui-action">Imported</Text>
                  <Card border="solid" rounding="sm" padding="fit">
                    <div className="divide-y divide-border-01">
                      {result.imported.map((item) => (
                        <div
                          key={item.skill.id}
                          className="flex items-start gap-2 px-3 py-2"
                        >
                          <div className="min-w-0 flex-1">
                            <Text font="main-ui-action">{item.skill.name}</Text>
                            {item.disabled_reason && (
                              <Text
                                as="p"
                                font="secondary-body"
                                color="text-03"
                              >
                                {item.disabled_reason}
                              </Text>
                            )}
                          </div>
                          <Tag
                            color={item.skill.enabled ? "green" : "gray"}
                            title={item.skill.enabled ? "Enabled" : "Disabled"}
                          />
                        </div>
                      ))}
                    </div>
                  </Card>
                </section>
              )}

              {resultNotImported.length > 0 && (
                <section className="flex flex-col gap-1.5">
                  <Text font="main-ui-action">Not imported</Text>
                  <Card border="solid" rounding="sm" padding="fit">
                    <div className="divide-y divide-border-01">
                      {resultNotImported.map((item) => (
                        <div
                          key={item.path}
                          className="flex flex-col gap-0.5 px-3 py-2"
                        >
                          <Text font="main-ui-action">{item.name}</Text>
                          <Text as="p" font="secondary-body" color="text-03">
                            {item.reason}
                          </Text>
                        </div>
                      ))}
                    </div>
                  </Card>
                </section>
              )}
            </div>
          ) : (
            <div className="flex w-full flex-col gap-3">
              <div className="flex flex-col gap-1">
                <Text font="main-ui-action">Repository</Text>
                <InputTypeIn
                  value={repository}
                  variant={loading ? "disabled" : "primary"}
                  placeholder="owner/repository or https://github.com/owner/repository"
                  onChange={(event) => onRepositoryChange(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") onSubmit();
                  }}
                />
              </div>

              <div className="flex items-center justify-between gap-2">
                <Text font="secondary-body" color="text-03">
                  {privateRepositoryMessage}
                </Text>
                {privateRepositoryAction && (
                  <Button
                    size="sm"
                    prominence="tertiary"
                    href={privateRepositoryAction.href}
                    rightIcon={SvgArrowRight}
                  >
                    {privateRepositoryAction.label}
                  </Button>
                )}
              </div>

              {error && (
                <MessageCard
                  variant="error"
                  title={
                    preview
                      ? "Couldn't import skills"
                      : "Couldn't load repository"
                  }
                  description={error}
                />
              )}

              {preview && (
                <div className="flex min-h-0 flex-col gap-2">
                  <div className="flex items-center gap-2">
                    <Checkbox
                      checked={allImportableSelected}
                      indeterminate={
                        selectedPaths.length > 0 && !allImportableSelected
                      }
                      disabled={loading || importablePaths.length === 0}
                      aria-label="Select all importable skills"
                      onCheckedChange={(checked) =>
                        onSelectedPathsChange(checked ? importablePaths : [])
                      }
                    />
                    <Text font="secondary-body" color="text-03">
                      {`${selectedPaths.length} of ${importablePaths.length} importable ${importablePaths.length === 1 ? "skill" : "skills"} selected`}
                    </Text>
                  </div>
                  <Card border="solid" rounding="sm" padding="fit">
                    <div className="max-h-80 divide-y divide-border-01 overflow-y-auto overscroll-contain">
                      {preview.skills.map((skill) => {
                        const unavailable = skill.unavailable_reason !== null;
                        const checked = selectedPathSet.has(skill.path);
                        return (
                          <div
                            key={skill.path}
                            className={cn(
                              "flex items-start gap-2 px-3 py-2",
                              unavailable && "opacity-50"
                            )}
                          >
                            <Checkbox
                              checked={checked}
                              disabled={loading || unavailable}
                              aria-label={`Select ${skill.name}`}
                              onCheckedChange={(nextChecked) =>
                                onSelectedPathsChange(
                                  nextChecked
                                    ? checked
                                      ? selectedPaths
                                      : [...selectedPaths, skill.path]
                                    : selectedPaths.filter(
                                        (path) => path !== skill.path
                                      )
                                )
                              }
                            />
                            <div className="min-w-0 flex-1">
                              <Text font="main-ui-action">{skill.name}</Text>
                              <Text
                                as="p"
                                font="secondary-body"
                                color="text-03"
                              >
                                {skill.unavailable_reason ??
                                  skill.description ??
                                  skill.path}
                              </Text>
                            </div>
                            {unavailable && (
                              <Tag color="amber" title="Can't import" />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </Card>
                </div>
              )}
            </div>
          )}
        </Modal.Body>
        <Modal.Footer>
          {result ? (
            <Button onClick={onClose}>Done</Button>
          ) : (
            <>
              <Button
                prominence="secondary"
                disabled={loading}
                onClick={onClose}
              >
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
                    : "Searching…"
                  : preview
                    ? `Import ${selectedPaths.length === 1 ? "skill" : `${selectedPaths.length} skills`}`
                    : "Search repository"}
              </Button>
            </>
          )}
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
