"use client";

import { useState } from "react";
import {
  Button,
  InputTypeIn,
  MessageCard,
  Switch,
  Text,
} from "@opal/components";
import { SvgDownloadCloud } from "@opal/icons";
import { markdown } from "@opal/utils";
import Modal from "@/refresh-components/Modal";
import { Section } from "@/layouts/general-layouts";
import { Content, ContentAction } from "@opal/layouts";
import {
  previewRepoSkills,
  installRepoSkills,
  type RepoSkillsPreview,
  type RepoSkillPreviewItem,
  type RepoSkillInstallFailure,
} from "@/lib/skills/api";
import { toast } from "@/hooks/useToast";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Step = "input" | "select" | "result";

interface AddSkillFromRepoModalProps {
  open: boolean;
  onClose: () => void;
  /** Invoked after at least one skill was successfully installed. */
  onInstalled: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AddSkillFromRepoModal({
  open,
  onClose,
  onInstalled,
}: AddSkillFromRepoModalProps) {
  const [step, setStep] = useState<Step>("input");
  const [source, setSource] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [preview, setPreview] = useState<RepoSkillsPreview | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [failures, setFailures] = useState<RepoSkillInstallFailure[]>([]);
  const [createdCount, setCreatedCount] = useState(0);

  function reset() {
    setStep("input");
    setSource("");
    setPreviewing(false);
    setInstalling(false);
    setPreviewError(null);
    setPreview(null);
    setSelected(new Set());
    setFailures([]);
    setCreatedCount(0);
  }

  function handleClose() {
    if (previewing || installing) return;
    reset();
    onClose();
  }

  function initSelection(skills: RepoSkillPreviewItem[]): Set<string> {
    const preSelected = skills.filter((s) => s.pre_selected).map((s) => s.slug);
    if (preSelected.length > 0) return new Set(preSelected);
    return new Set(skills.map((s) => s.slug));
  }

  async function handleFindSkills() {
    if (!source.trim()) return;
    setPreviewing(true);
    setPreviewError(null);
    try {
      const result = await previewRepoSkills(source.trim());
      setPreview(result);
      setSelected(initSelection(result.skills));
      setStep("select");
    } catch (err) {
      setPreviewError(
        err instanceof Error ? err.message : "Failed to fetch skills from repo"
      );
    } finally {
      setPreviewing(false);
    }
  }

  function toggleSkill(slug: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) {
        next.delete(slug);
      } else {
        next.add(slug);
      }
      return next;
    });
  }

  async function handleInstall() {
    if (!preview || selected.size === 0) return;
    setInstalling(true);
    try {
      const result = await installRepoSkills(source.trim(), [...selected]);
      setCreatedCount(result.created.length);
      if (result.created.length > 0) {
        onInstalled();
        if (result.failures.length === 0) {
          toast.success(
            `Installed ${result.created.length} skill${result.created.length === 1 ? "" : "s"}`
          );
          reset();
          onClose();
          return;
        }
        toast.success(
          `Installed ${result.created.length} skill${result.created.length === 1 ? "" : "s"} with some failures`
        );
      }
      // partial or total failure — stay open and show the failure list
      setFailures(result.failures);
      setStep("result");
    } catch (err) {
      setCreatedCount(0);
      setFailures([
        {
          slug: "*",
          error:
            err instanceof Error ? err.message : "Installation request failed",
        },
      ]);
      setStep("result");
    } finally {
      setInstalling(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------

  function renderInputStep() {
    return (
      <>
        <Modal.Body>
          <Section gap={0.5} alignItems="stretch">
            <Section gap={0.25} alignItems="stretch">
              <Text as="p" font="main-ui-action" color="text-05">
                {markdown("GitHub repo URL or `npx skills add` command")}
              </Text>
              <InputTypeIn
                placeholder="https://github.com/owner/repo  or  npx skills add <url>"
                value={source}
                onChange={(e) => {
                  setSource(e.target.value);
                  setPreviewError(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && source.trim() && !previewing) {
                    void handleFindSkills();
                  }
                }}
                autoFocus
              />
              <Text as="p" font="secondary-body" color="text-03">
                Paste a GitHub URL, an owner/repo slug, or the full npx skills
                add … command from a skills.sh-compatible repo.
              </Text>
            </Section>

            {previewError && (
              <MessageCard
                variant="error"
                title="Could not fetch skills"
                description={previewError}
              />
            )}
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            icon={SvgDownloadCloud}
            disabled={!source.trim() || previewing}
            onClick={() => void handleFindSkills()}
          >
            {previewing ? "Fetching…" : "Find skills"}
          </Button>
        </Modal.Footer>
      </>
    );
  }

  function renderSelectStep() {
    if (!preview) return null;
    const { source_label, ref: repoRef, skills } = preview;
    const skillCountLabel = `${skills.length} skill${skills.length === 1 ? "" : "s"} found. Toggle which ones to install.`;
    const sourceHeading = repoRef
      ? `${source_label} @ ${repoRef}`
      : source_label;

    return (
      <>
        <Modal.Body>
          <Section gap={0.75} alignItems="stretch">
            <Section gap={0.25} alignItems="stretch">
              <Text font="main-ui-action" color="text-05">
                {sourceHeading}
              </Text>
              <Text font="secondary-body" color="text-03">
                {skillCountLabel}
              </Text>
            </Section>

            <Section gap={0.25} alignItems="stretch">
              {skills.map((skill) => (
                <ContentAction
                  key={skill.slug}
                  sizePreset="main-ui"
                  variant="section"
                  title={skill.name}
                  description={skill.description}
                  padding="sm"
                  rightChildren={
                    <Switch
                      checked={selected.has(skill.slug)}
                      onCheckedChange={() => toggleSkill(skill.slug)}
                      disabled={installing}
                      aria-label={skill.name}
                    />
                  }
                />
              ))}
            </Section>
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <Button
            prominence="secondary"
            onClick={() => {
              setStep("input");
              setPreview(null);
              setSelected(new Set());
            }}
            disabled={installing}
          >
            Back
          </Button>
          <Button
            icon={SvgDownloadCloud}
            disabled={selected.size === 0 || installing}
            onClick={() => void handleInstall()}
          >
            {installing
              ? "Installing…"
              : `Install ${selected.size} skill${selected.size === 1 ? "" : "s"}`}
          </Button>
        </Modal.Footer>
      </>
    );
  }

  function renderResultStep() {
    const allFailed = createdCount === 0;
    return (
      <>
        <Modal.Body>
          <Section gap={0.5} alignItems="stretch">
            <MessageCard
              variant={allFailed ? "error" : "warning"}
              title={
                allFailed
                  ? "No skills were installed"
                  : "Some skills failed to install"
              }
              description={
                allFailed
                  ? "Every selected skill encountered an error. Nothing was added."
                  : `Installed ${createdCount} skill${createdCount === 1 ? "" : "s"}. The skills below encountered errors.`
              }
            />
            <Section gap={0.25} alignItems="stretch">
              {failures.map((f) => (
                <Content
                  key={f.slug}
                  sizePreset="main-ui"
                  variant="section"
                  title={f.slug}
                  description={f.error}
                  color="danger"
                />
              ))}
            </Section>
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={handleClose}>Done</Button>
        </Modal.Footer>
      </>
    );
  }

  // ---------------------------------------------------------------------------
  // Modal header props per step
  // ---------------------------------------------------------------------------

  const headerProps =
    step === "input"
      ? {
          title: "Add skills from repo",
          description:
            "Install agent skills directly from a GitHub repository. Paste a URL, owner/repo, or a skills.sh npx command.",
        }
      : step === "select"
        ? {
            title: "Select skills to install",
            description:
              "Choose which skills from this repo you want to add to your personal skill library.",
          }
        : createdCount === 0
          ? {
              title: "Installation failed",
              description: "None of the selected skills could be installed.",
            }
          : {
              title: "Install complete",
              description:
                "Some skills were installed; others encountered errors.",
            };

  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <Modal.Content width="md">
        <Modal.Header
          icon={SvgDownloadCloud}
          title={headerProps.title}
          description={headerProps.description}
          onClose={handleClose}
        />
        {step === "input" && renderInputStep()}
        {step === "select" && renderSelectStep()}
        {step === "result" && renderResultStep()}
      </Modal.Content>
    </Modal>
  );
}
