"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, MessageCard, Text } from "@opal/components";
import { Section, toast } from "@opal/layouts";
import { SvgEdit } from "@opal/icons";
import {
  composeSkillMarkdown,
  parseSkillMarkdown,
} from "@/lib/customize/skillMarkdown";
import {
  isSkillVersionStale,
  patchUserSkill,
  removeUserSkillFile,
  uploadUserSkillFiles,
} from "@/lib/skills/api";
import type { PreparedSkillFilesUpload } from "@/lib/skills/bundleUpload";
import { useSkillLimitCopy } from "@/lib/skills/hooks";
import type { SkillBundleFile, SkillEditableDetail } from "@/lib/skills/types";
import { type InstructionsDisplayMode } from "@/sections/skills/InstructionsDisplayModeToggle";
import SkillBundleEditor, {
  bundleFiles,
  uploadPaths,
} from "@/sections/customize/SkillBundleEditor";

interface SkillContentsTabProps {
  name: string;
  description: string;
  versionNumber: number | null;
  instructions: string | undefined;
  /** The supporting files; null until they load. */
  files: readonly SkillBundleFile[] | null;
  /** The editable skill; undefined for a user who may not edit it. */
  detail: SkillEditableDetail | undefined;
  locked?: boolean;
  editing: boolean;
  onEditingChange: (editing: boolean) => void;
  /** Tells the page whether there are unsaved edits, for its leave guard. */
  onDirtyChange: (dirty: boolean) => void;
  /** Runs `leave` now, or after the user confirms losing unsaved edits. */
  confirmLeave: (leave: () => void) => void;
  /** Reloads the skill; resolves to whether the newest version loaded. */
  onSaved: () => Promise<boolean>;
}

/** What the user started from: each save step is based on `versionId`, so a
 * newer save by someone else is refused instead of overwritten. */
interface EditBase {
  versionId: string | null;
  description: string;
  instructions: string;
  text: string;
}

function editBaseOf(detail: SkillEditableDetail): EditBase {
  return {
    versionId: detail.current_version_id,
    description: detail.description,
    instructions: detail.instructions_markdown.trimEnd(),
    text: composeSkillMarkdown({
      name: detail.name,
      description: detail.description,
      instructions: detail.instructions_markdown,
    }),
  };
}

/** The Contents tab: the files of the skill beside a viewer. Edit changes the
 * same view in place, and Save version saves the changes. */
export default function SkillContentsTab({
  name,
  description,
  versionNumber,
  instructions,
  files,
  detail,
  locked = false,
  editing,
  onEditingChange,
  onDirtyChange,
  confirmLeave,
  onSaved,
}: SkillContentsTabProps) {
  const t = useTranslations("customize.skillPage.contents");
  const skillCopy = useTranslations("skills");
  const versionsCopy = useTranslations("skills.modals.versions");
  const { describeError } = useSkillLimitCopy();
  // Unset: the source while editing, the rendered text otherwise.
  const [chosenMode, setMode] = useState<InstructionsDisplayMode | null>(null);
  const mode = chosenMode ?? (editing ? "raw" : "rendered");
  const [base, setBase] = useState<EditBase | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [added, setAdded] = useState<PreparedSkillFilesUpload[]>([]);
  const [removed, setRemoved] = useState<ReadonlySet<string>>(new Set());
  const [preparing, setPreparing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [stale, setStale] = useState(false);
  // Paths a save uploaded, so a retry can still remove one of them.
  const uploadedPaths = useRef<Set<string>>(new Set());
  // A save that ends after the user left must not navigate back here.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  if (editing && detail && base === null) setBase(editBaseOf(detail));

  const original = composeSkillMarkdown({
    name,
    description,
    instructions: instructions ?? "",
  });
  const text = draft ?? base?.text ?? original;
  const dirty =
    editing &&
    ((draft !== null && draft !== base?.text) ||
      added.length > 0 ||
      removed.size > 0);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  const listed = bundleFiles(files ?? [], added, removed);
  const preview = editing
    ? (() => {
        const parsed = parseSkillMarkdown(text);
        return parsed.ok ? parsed.instructions : text;
      })()
    : (instructions ?? "");

  function reset(): void {
    setBase(null);
    setDraft(null);
    setAdded([]);
    setRemoved(new Set());
    setMode(null);
    setStale(false);
    uploadedPaths.current = new Set();
  }

  function startEditing(): void {
    reset();
    onEditingChange(true);
  }

  function stopEditing(): void {
    reset();
    onEditingChange(false);
  }

  function reload(): void {
    // Staged files are dropped with the text: they were based on the version
    // that was refused. A failed load keeps them for another Reload.
    void onSaved().then((loaded) => {
      if (loaded) reset();
      else toast.error(t("reloadFailed"));
    });
  }

  function add(upload: PreparedSkillFilesUpload): void {
    if (upload.containsSkillMd) {
      toast.error(t("errors.skillMd"));
      return;
    }
    setAdded((current) => [...current, upload]);
    // A new file replaces a saved one that was marked for removal.
    const paths = new Set(uploadPaths(upload));
    setRemoved(
      (current) => new Set([...current].filter((path) => !paths.has(path)))
    );
  }

  function remove(path: string): void {
    setRemoved((current) => new Set([...current, path]));
  }

  async function save(): Promise<void> {
    if (!detail || !base || saving) return;
    const parsed = parseSkillMarkdown(text);
    if (!parsed.ok) {
      toast.error(t(`errors.${parsed.error}`));
      return;
    }
    if (parsed.name !== detail.name) {
      toast.error(t("errors.name", { name: detail.name }));
      return;
    }
    setSaving(true);
    let versionId = base.versionId;
    try {
      if (
        parsed.description !== base.description ||
        parsed.instructions !== base.instructions
      ) {
        const updated = await patchUserSkill(detail.id, {
          description: parsed.description,
          instructions_markdown: parsed.instructions,
          base_version_id: versionId,
        });
        versionId = updated.current_version_id;
        const saved: EditBase = {
          versionId,
          description: parsed.description,
          instructions: parsed.instructions,
          text,
        };
        setBase(saved);
      }
      // A staged file that was removed again is not uploaded.
      const uploads = added.filter((upload) =>
        uploadPaths(upload).some((path) => !removed.has(path))
      );
      const present = new Set([
        ...(files ?? []).map((file) => file.path),
        ...uploadedPaths.current,
      ]);
      for (const upload of uploads) {
        const updated = await uploadUserSkillFiles(
          detail.id,
          upload.file,
          versionId
        );
        versionId = updated.current_version_id;
        uploadPaths(upload).forEach((path) => {
          present.add(path);
          uploadedPaths.current.add(path);
        });
        setAdded((current) => current.filter((item) => item !== upload));
        setBase((current) => current && { ...current, versionId });
      }
      for (const path of removed) {
        if (!present.has(path)) continue;
        const updated = await removeUserSkillFile(detail.id, path, versionId);
        versionId = updated.current_version_id;
        setRemoved(
          (current) => new Set([...current].filter((item) => item !== path))
        );
        setBase((current) => current && { ...current, versionId });
      }
      toast.success(skillCopy("editor.toasts.saved", { name: detail.name }));
      if (mounted.current) stopEditing();
      // The rest of the page shows the saved skill even after the user left.
      await onSaved();
    } catch (error) {
      // The steps that finished are kept; Save tries only the rest.
      if (isSkillVersionStale(error)) setStale(true);
      else
        toast.error(
          describeError(error, skillCopy("editor.toasts.saveFailed"))
        );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section gap={2} alignItems="stretch" height="auto">
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="center"
        height="auto"
        gap={1}
      >
        <Text font="main-ui-action" color="text-04">
          {versionNumber === null
            ? name
            : t("version", { name, version: versionNumber })}
        </Text>
        {detail &&
          !locked &&
          (editing ? (
            <Section
              flexDirection="row"
              justifyContent="end"
              width="auto"
              height="auto"
              gap={0.5}
            >
              <Button
                prominence="secondary"
                disabled={saving}
                onClick={() => confirmLeave(stopEditing)}
              >
                {t("cancel")}
              </Button>
              <Button
                disabled={!dirty || saving || preparing || stale}
                onClick={() => void save()}
              >
                {saving ? t("saving") : t("saveVersion")}
              </Button>
            </Section>
          ) : (
            <Button
              prominence="secondary"
              icon={SvgEdit}
              onClick={startEditing}
            >
              {t("edit")}
            </Button>
          ))}
      </Section>

      {locked && (
        <Text as="p" font="secondary-body" color="text-03">
          {versionsCopy("locked")}
        </Text>
      )}

      {stale && (
        <MessageCard
          variant="warning"
          title={skillCopy("editor.staleVersion.title")}
          description={skillCopy("editor.staleVersion.description")}
          rightChildren={
            <Button prominence="secondary" onClick={reload}>
              {skillCopy("editor.staleVersion.reload.label")}
            </Button>
          }
        />
      )}

      <SkillBundleEditor
        files={listed}
        editing={editing}
        text={editing ? text : original}
        onTextChange={setDraft}
        preview={preview}
        mode={mode}
        onModeChange={setMode}
        busy={saving}
        onAdd={add}
        onRemove={remove}
        onPreparingChange={setPreparing}
        addedFileNote={t("addedFile")}
      />
    </Section>
  );
}
