"use client";

import { Button, Tag } from "@opal/components";
import {
  SvgCode,
  SvgDownload,
  SvgFileText,
  SvgInfo,
  SvgTerminal,
  SvgUploadCloud,
} from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import { Content } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import type {
  CustomSkill,
  SkillBundleFile,
  SkillFileKind,
} from "@/refresh-pages/admin/SkillsPage/interfaces";
import {
  formatBytes,
  formatRelativeTime,
  shortFingerprint,
  summarizeVisibility,
} from "@/refresh-pages/admin/SkillsPage/helpers";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface InspectSkillModalProps {
  skill: CustomSkill | null;
  open: boolean;
  onClose: () => void;
  onReplaceBundle?: () => void;
  onDownload?: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fileIcon(kind: SkillFileKind) {
  switch (kind) {
    case "markdown":
      return SvgFileText;
    case "script":
      return SvgCode;
    case "executable":
      return SvgTerminal;
    case "binary":
      return SvgFileText;
    case "data":
      return SvgFileText;
  }
}

function FileRow({ file }: { file: SkillBundleFile }) {
  return (
    <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-border-01 last:border-b-0">
      <Content
        sizePreset="main-ui"
        variant="section"
        icon={fileIcon(file.kind)}
        title={file.path}
        description={formatBytes(file.size_bytes)}
      />
      {file.executable && <Tag title="Executable" color="purple" />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function InspectSkillModal({
  skill,
  open,
  onClose,
  onReplaceBundle,
  onDownload,
}: InspectSkillModalProps) {
  if (!skill) return null;

  const summary = summarizeVisibility(skill);

  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="lg">
        <Modal.Header
          icon={SvgInfo}
          title={skill.name}
          description={skill.description}
          onClose={onClose}
        />
        <Modal.Body>
          <Section gap={1.25} alignItems="stretch">
            {/* Metadata grid */}
            <div className="grid grid-cols-2 gap-3 p-3 rounded-md border border-border-02 bg-background-tint-01">
              <Section gap={0.25} alignItems="start">
                <Text as="span" secondaryAction text03>
                  Slug
                </Text>
                <Text as="span" mainUiBody text05>
                  {skill.slug}
                </Text>
              </Section>
              <Section gap={0.25} alignItems="start">
                <Text as="span" secondaryAction text03>
                  Author
                </Text>
                <Text as="span" mainUiBody text05>
                  {skill.author.name}
                  {skill.author.is_admin ? " (admin)" : ""}
                </Text>
              </Section>
              <Section gap={0.25} alignItems="start">
                <Text as="span" secondaryAction text03>
                  Visibility
                </Text>
                <Text as="span" mainUiBody text05>
                  {summary.label}
                  {summary.description ? ` — ${summary.description}` : ""}
                </Text>
              </Section>
              <Section gap={0.25} alignItems="start">
                <Text as="span" secondaryAction text03>
                  Updated
                </Text>
                <Text as="span" mainUiBody text05>
                  {formatRelativeTime(skill.updated_at)}
                </Text>
              </Section>
              <Section gap={0.25} alignItems="start">
                <Text as="span" secondaryAction text03>
                  Bundle size
                </Text>
                <Text as="span" mainUiBody text05>
                  {formatBytes(skill.bundle.total_bytes)}
                </Text>
              </Section>
              <Section gap={0.25} alignItems="start">
                <Text as="span" secondaryAction text03>
                  Fingerprint
                </Text>
                <Text as="span" mainUiBody text05>
                  {shortFingerprint(skill.bundle.sha256)}…
                </Text>
              </Section>
            </div>

            {!skill.enabled && skill.admin_disabled_reason && (
              <div className="p-3 rounded-md border border-status-warning-03 bg-status-warning-01">
                <Section gap={0.25} alignItems="start">
                  <Text as="span" mainUiAction text05>
                    Disabled by admin
                  </Text>
                  <Text as="span" mainUiBody text03>
                    {skill.admin_disabled_reason}
                  </Text>
                </Section>
              </div>
            )}

            {skill.promotion_requested && !skill.promoted_by_admin && (
              <div className="p-3 rounded-md border border-action-link-03 bg-action-link-01">
                <Text as="span" mainUiBody text05>
                  This skill&apos;s author has requested org-wide promotion.
                </Text>
              </div>
            )}

            {/* File tree */}
            <Section gap={0.5} alignItems="stretch">
              <Text as="span" mainUiAction text05>
                Bundle contents ({skill.bundle.files.length} files)
              </Text>
              <div className="rounded-md border border-border-02 bg-background-neutral-00">
                {skill.bundle.files.map((file) => (
                  <FileRow key={file.path} file={file} />
                ))}
              </div>
            </Section>
          </Section>
        </Modal.Body>
        <Modal.Footer>
          {onDownload && (
            <Button
              prominence="secondary"
              icon={SvgDownload}
              onClick={onDownload}
            >
              Download zip
            </Button>
          )}
          {onReplaceBundle && (
            <Button icon={SvgUploadCloud} onClick={onReplaceBundle}>
              Replace bundle
            </Button>
          )}
          <Button prominence="secondary" onClick={onClose}>
            Close
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
