"use client";

import { useEffect, useRef, useState } from "react";
import Modal from "@/refresh-components/Modal";
import {
  Button,
  InputTypeIn,
  MessageCard,
  Text,
  Tooltip,
} from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import { cn } from "@opal/utils";
import { Content, Section } from "@opal/layouts";
import { ListFieldInput } from "@/refresh-components/inputs/ListFieldInput";
import InputKeyValue, {
  KeyValue,
} from "@/refresh-components/inputs/InputKeyValue";
import { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";
import {
  createCustomExternalApp,
  createCustomExternalAppFromRepo,
  replaceCustomAppBundle,
  updateExternalApp,
} from "@/app/craft/services/externalAppsService";
import {
  previewRepoSkillsAdmin,
  type RepoSkillPreviewItem,
  type RepoSkillsPreview,
} from "@/lib/skills/api";

interface CreateCustomAppModalProps {
  open: boolean;
  onClose: () => void;
  /** Invoked after a successful create/edit so callers can refresh their list. */
  onSaved: () => void;
  /** Null → create a new custom app; non-null → edit that app's config. */
  existingApp: ExternalAppAdminResponse | null;
}

/** Collapse a key-value list into a record, dropping rows with an empty key. */
function toRecord(items: KeyValue[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const { key, value } of items) {
    const trimmedKey = key.trim();
    if (trimmedKey) out[trimmedKey] = value;
  }
  return out;
}

/** Expand a record into editable rows, seeding one empty row when empty. */
function toKeyValues(record: Record<string, string>): KeyValue[] {
  const entries = Object.entries(record).map(([key, value]) => ({
    key,
    value,
  }));
  return entries.length > 0 ? entries : [{ key: "", value: "" }];
}

type BundleSource = "upload" | "repo";

export default function CreateCustomAppModal({
  open,
  onClose,
  onSaved,
  existingApp,
}: CreateCustomAppModalProps) {
  const isEdit = existingApp !== null;

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [upstreamPatterns, setUpstreamPatterns] = useState<string[]>([]);
  const [headers, setHeaders] = useState<KeyValue[]>([{ key: "", value: "" }]);
  const [orgCredentials, setOrgCredentials] = useState<KeyValue[]>([
    { key: "", value: "" },
  ]);
  const [file, setFile] = useState<File | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Repo-import state (create mode only)
  const [bundleSource, setBundleSource] = useState<BundleSource>("upload");
  const [repoSource, setRepoSource] = useState("");
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [repoPreview, setRepoPreview] = useState<RepoSkillsPreview | null>(
    null
  );
  const [repoPreviewError, setRepoPreviewError] = useState<string | null>(null);
  const [selectedSkill, setSelectedSkill] =
    useState<RepoSkillPreviewItem | null>(null);

  // Re-seed every time the modal opens: from the existing app when editing,
  // blank when creating. Prevents a prior attempt from leaking in.
  useEffect(() => {
    if (!open) return;
    setName(existingApp?.name ?? "");
    setDescription(existingApp?.description ?? "");
    setUpstreamPatterns(existingApp?.upstream_url_patterns ?? []);
    setHeaders(
      existingApp
        ? toKeyValues(existingApp.auth_template)
        : [{ key: "", value: "" }]
    );
    setOrgCredentials(
      existingApp
        ? toKeyValues(existingApp.organization_credentials)
        : [{ key: "", value: "" }]
    );
    setFile(null);
    setError(null);
    setBundleSource("upload");
    setRepoSource("");
    setIsPreviewing(false);
    setRepoPreview(null);
    setRepoPreviewError(null);
    setSelectedSkill(null);
  }, [open, existingApp]);

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
  }

  async function handleFindSkills() {
    if (!repoSource.trim()) return;
    setIsPreviewing(true);
    setRepoPreviewError(null);
    setRepoPreview(null);
    setSelectedSkill(null);
    try {
      const result = await previewRepoSkillsAdmin(repoSource.trim());
      setRepoPreview(result);
    } catch (err) {
      setRepoPreviewError(
        err instanceof Error ? err.message : "Failed to fetch skills from repo"
      );
    } finally {
      setIsPreviewing(false);
    }
  }

  function selectSkill(skill: RepoSkillPreviewItem) {
    setSelectedSkill(skill);
    // Prefill name/description only when they're still blank
    if (!name.trim()) setName(skill.name);
    if (!description.trim()) setDescription(skill.description);
  }

  // Headers and org credentials are optional; name + at least one upstream
  // pattern are required. A bundle is required only on create (optional on edit).
  const disabledCreateReason = (() => {
    if (isSaving) return "Save is already in progress.";
    if (name.trim().length === 0) {
      return "Enter a name before creating this custom app.";
    }
    if (upstreamPatterns.length === 0) {
      return "Add at least one upstream URL pattern. Type a pattern and press Enter.";
    }
    if (!isEdit) {
      if (bundleSource === "upload" && file === null) {
        return "Upload a bundle .zip file before creating this custom app.";
      }
      if (bundleSource === "repo" && selectedSkill === null) {
        return "Select a skill from the repo before creating this custom app.";
      }
    }
    return null;
  })();
  const createButton = (
    <Button onClick={save} disabled={disabledCreateReason !== null}>
      {isSaving
        ? isEdit
          ? "Saving…"
          : "Creating…"
        : isEdit
          ? "Save"
          : "Create"}
    </Button>
  );

  async function save() {
    setIsSaving(true);
    setError(null);
    // Edit is two calls (bundle + fields); track the bundle step to message
    // partial success accurately.
    let bundleSaved = false;
    try {
      if (existingApp) {
        // Bundle first (the failure-prone step): a failure here leaves fields
        // unsent. Clear the file so a retry doesn't re-upload it.
        if (file) {
          await replaceCustomAppBundle(existingApp.id, file);
          setFile(null);
          bundleSaved = true;
        }
        // enabled is toggled separately on the card.
        await updateExternalApp(existingApp.id, {
          name: name.trim(),
          description: description.trim(),
          upstream_url_patterns: upstreamPatterns,
          auth_template: toRecord(headers),
          organization_credentials: toRecord(orgCredentials),
        });
      } else if (bundleSource === "repo") {
        // Create from repo: selectedSkill is guaranteed non-null by disabledCreateReason.
        await createCustomExternalAppFromRepo({
          name: name.trim(),
          description: description.trim(),
          upstream_url_patterns: upstreamPatterns,
          auth_template: toRecord(headers),
          organization_credentials: toRecord(orgCredentials),
          enabled: true,
          source: repoSource.trim(),
          slug: selectedSkill!.slug,
        });
      } else {
        // Create via zip upload: bundle is required (enforced by disabledCreateReason).
        await createCustomExternalApp({
          name: name.trim(),
          description: description.trim(),
          upstream_url_patterns: upstreamPatterns,
          auth_template: toRecord(headers),
          organization_credentials: toRecord(orgCredentials),
          enabled: true,
          bundle: file!,
        });
      }
      onSaved();
      onClose();
    } catch (e) {
      // A step may have committed; refresh the list to reflect what persisted.
      onSaved();
      const detail = e instanceof Error ? e.message : String(e);
      setError(
        bundleSaved
          ? `The new bundle was saved, but updating the other fields failed — retry to finish: ${detail}`
          : detail
      );
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()}>
      <Modal.Content width="lg" height="lg">
        <Modal.Header
          title={existingApp ? `Edit ${existingApp.name}` : "Create custom app"}
          description={
            isEdit
              ? "Update this custom app's configuration, and optionally upload a new bundle to replace its files."
              : "Define a custom external app: upload its skill bundle and configure how the egress proxy authenticates outbound requests."
          }
        />
        <Modal.Body>
          <Section gap={1} alignItems="stretch">
            <Section gap={0.25} alignItems="stretch">
              <Text font="main-ui-action">Name</Text>
              <InputTypeIn
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="My Custom App"
              />
            </Section>

            <Section gap={0.25} alignItems="stretch">
              <Text font="main-ui-action">Description</Text>
              <InputTypeIn
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional — defaults to the bundle's SKILL.md description"
              />
            </Section>

            <Section gap={0.25} alignItems="stretch">
              <Text font="main-ui-action">Upstream URL patterns</Text>
              <Text font="secondary-body" color="text-03">
                {
                  "Outbound URLs the proxy may inject credentials into. Use * to match any characters (e.g. https://api.example.com/* covers every path on that host). The host must be literal — no wildcards before the first slash. Type a pattern and press Enter."
                }
              </Text>
              <ListFieldInput
                values={upstreamPatterns}
                onChange={setUpstreamPatterns}
                placeholder="https://api.example.com/*"
              />
            </Section>

            <Section gap={0.25} alignItems="stretch">
              <Text font="main-ui-action">Header credential pattern</Text>
              <Text font="secondary-body" color="text-03">
                {`Optional — headers injected into outbound requests. Use {placeholder} for values the user (or org below) supplies, e.g. "Bearer {api_key}". Leave empty to allowlist the upstream patterns without injecting credentials.`}
              </Text>
              <InputKeyValue
                keyTitle="Header"
                valueTitle="Value"
                keyPlaceholder="Authorization"
                valuePlaceholder="Bearer {api_key}"
                items={headers}
                onChange={setHeaders}
                mode="line"
                addButtonLabel="Add header"
              />
            </Section>

            <Section gap={0.25} alignItems="stretch">
              <Text font="main-ui-action">Organization credentials</Text>
              <Text font="secondary-body" color="text-03">
                Optional — values your org pre-fills for every user. Leave empty
                for apps where each user supplies their own credentials.
              </Text>
              <InputKeyValue
                keyTitle="Credential key"
                valueTitle="Value"
                keyPlaceholder="api_key"
                valuePlaceholder="sk-…"
                items={orgCredentials}
                onChange={setOrgCredentials}
                mode="line"
                addButtonLabel="Add credential"
              />
            </Section>

            <Section gap={0.5} alignItems="stretch">
              <Section gap={0.25} alignItems="stretch">
                <Text font="main-ui-action">
                  {isEdit ? "Replace bundle (.zip)" : "Bundle"}
                </Text>
                {!isEdit && (
                  <Text font="secondary-body" color="text-03">
                    Upload a zip or import a skill directly from a git repo.
                  </Text>
                )}
                {isEdit && (
                  <Text font="secondary-body" color="text-03">
                    Optional — upload a new zip to replace the current bundle.
                    Leave empty to keep it. The slug stays the same.
                  </Text>
                )}
              </Section>

              {/* Bundle-source toggle — create mode only */}
              {!isEdit && (
                <Section
                  flexDirection="row"
                  gap={0.25}
                  alignItems="center"
                  justifyContent="start"
                  width="fit"
                >
                  <Button
                    prominence={
                      bundleSource === "upload" ? "primary" : "secondary"
                    }
                    size="sm"
                    onClick={() => setBundleSource("upload")}
                  >
                    Upload zip
                  </Button>
                  <Button
                    prominence={
                      bundleSource === "repo" ? "primary" : "secondary"
                    }
                    size="sm"
                    onClick={() => setBundleSource("repo")}
                  >
                    Import from repo
                  </Button>
                </Section>
              )}

              {/* Upload zip mode */}
              {(isEdit || bundleSource === "upload") && (
                <Section
                  flexDirection="row"
                  gap={0.5}
                  alignItems="center"
                  justifyContent="start"
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".zip,application/zip"
                    onChange={handleFileChange}
                    className="hidden"
                  />
                  <Button
                    icon={SvgUploadCloud}
                    prominence="secondary"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    {file
                      ? "Change file"
                      : isEdit
                        ? "Choose new zip"
                        : "Choose zip"}
                  </Button>
                  <Text font="main-ui-body" color="text-03">
                    {file
                      ? file.name
                      : isEdit
                        ? "Keeping current bundle"
                        : "No file selected"}
                  </Text>
                </Section>
              )}

              {/* Import from repo mode */}
              {!isEdit && bundleSource === "repo" && (
                <Section gap={0.5} alignItems="stretch">
                  <Section
                    flexDirection="row"
                    gap={0.5}
                    alignItems="center"
                    justifyContent="start"
                  >
                    <div className="flex-1">
                      <InputTypeIn
                        placeholder="https://github.com/owner/repo  or  npx skills add <url>"
                        value={repoSource}
                        onChange={(e) => {
                          setRepoSource(e.target.value);
                          setRepoPreviewError(null);
                          // Editing the source invalidates the previous repo's
                          // discovery — clear it so Create can't submit a stale
                          // skill slug against a different source.
                          setRepoPreview(null);
                          setSelectedSkill(null);
                        }}
                        onKeyDown={(e) => {
                          if (
                            e.key === "Enter" &&
                            repoSource.trim() &&
                            !isPreviewing
                          ) {
                            void handleFindSkills();
                          }
                        }}
                      />
                    </div>
                    <Button
                      prominence="secondary"
                      disabled={!repoSource.trim() || isPreviewing}
                      onClick={() => void handleFindSkills()}
                    >
                      {isPreviewing ? "Fetching…" : "Find skills"}
                    </Button>
                  </Section>
                  <Text font="secondary-body" color="text-03">
                    Paste a GitHub URL, an owner/repo slug, or the full npx
                    skills add … command. One skill will become the app bundle.
                  </Text>

                  {repoPreviewError && (
                    <MessageCard
                      variant="error"
                      title="Could not fetch skills"
                      description={repoPreviewError}
                    />
                  )}

                  {repoPreview && repoPreview.skills.length > 0 && (
                    <Section
                      gap={0.25}
                      alignItems="stretch"
                      role="radiogroup"
                      aria-label="Skills found in repository"
                    >
                      <Text font="secondary-body" color="text-03">
                        {`${repoPreview.skills.length} skill${repoPreview.skills.length === 1 ? "" : "s"} found — select one to use as the bundle.`}
                      </Text>
                      {repoPreview.skills.map((skill) => {
                        const isSelected = selectedSkill?.slug === skill.slug;
                        return (
                          // A fixed-height Interactive.Container can't hold a
                          // multi-line title+description, so this selectable
                          // card uses a content-sized wrapper with design
                          // tokens for the selected state.
                          <div
                            key={skill.slug}
                            role="radio"
                            aria-checked={isSelected}
                            tabIndex={0}
                            onClick={() => selectSkill(skill)}
                            onKeyDown={(e: React.KeyboardEvent) => {
                              if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                selectSkill(skill);
                              }
                            }}
                            className={cn(
                              "cursor-pointer rounded-md border p-2",
                              isSelected
                                ? "bg-background-tint-02 border-border-04"
                                : "bg-background-neutral-02 border-border-02"
                            )}
                          >
                            <Content
                              sizePreset="main-ui"
                              variant="section"
                              title={skill.name}
                              description={skill.description}
                              descriptionMaxLines={2}
                            />
                          </div>
                        );
                      })}
                    </Section>
                  )}

                  {repoPreview && repoPreview.skills.length === 0 && (
                    <MessageCard
                      variant="warning"
                      title="No skills found"
                      description="This repo doesn't appear to contain any skills.sh-compatible skills."
                    />
                  )}
                </Section>
              )}
            </Section>

            {error && (
              <MessageCard
                variant="error"
                title="Couldn't save"
                description={error}
              />
            )}
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <Section
            flexDirection="row"
            justifyContent="end"
            gap={0.5}
            height="auto"
          >
            <Button
              prominence="secondary"
              onClick={onClose}
              disabled={isSaving}
            >
              Cancel
            </Button>
            {disabledCreateReason ? (
              <Tooltip tooltip={disabledCreateReason}>
                <span className="inline-flex">{createButton}</span>
              </Tooltip>
            ) : (
              createButton
            )}
          </Section>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
