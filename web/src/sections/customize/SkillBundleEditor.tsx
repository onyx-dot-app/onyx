"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  CompactMarkdown,
  InputTextArea,
  LineItemButton,
  Text,
} from "@opal/components";
import { Section, SplitCard, toast } from "@opal/layouts";
import { SvgFileText, SvgPlus, SvgTrash } from "@opal/icons";
import type { RichStr } from "@opal/types";
import type { PreparedSkillFilesUpload } from "@/lib/skills/bundleUpload";
import SkillFilesPicker from "@/sections/skills/SkillFilesPicker";
import InstructionsDisplayModeToggle, {
  type InstructionsDisplayMode,
} from "@/sections/skills/InstructionsDisplayModeToggle";

export const SKILL_MD = "SKILL.md";

export interface BundleFile {
  path: string;
  size: number | null;
  /** Added in this edit, not saved yet. */
  added: boolean;
}

/** The paths an upload adds: its entries, or its own name. */
export function uploadPaths(upload: PreparedSkillFilesUpload): string[] {
  return (upload.entries ?? [{ path: upload.displayName }]).map(
    (entry) => entry.path
  );
}

/** The files to list: the saved ones, then the added ones, where an added
 * path replaces a saved one, without the removed paths, sorted by path. */
export function bundleFiles(
  saved: readonly { path: string; size: number | null }[],
  added: readonly PreparedSkillFilesUpload[],
  removed: ReadonlySet<string>
): BundleFile[] {
  const byPath = new Map<string, BundleFile>();
  for (const file of saved)
    byPath.set(file.path, { path: file.path, size: file.size, added: false });
  for (const upload of added)
    for (const entry of upload.entries ?? [
      { path: upload.displayName, size: upload.file.size },
    ])
      byPath.set(entry.path, {
        path: entry.path,
        size: entry.size,
        added: true,
      });
  return [...byPath.values()]
    .filter((file) => !removed.has(file.path))
    .sort((a, b) => a.path.localeCompare(b.path));
}

interface SkillBundleEditorProps {
  /** The supporting files, without SKILL.md. */
  files: readonly BundleFile[];
  editing: boolean;
  /** The SKILL.md source. */
  text: string;
  onTextChange: (text: string) => void;
  /** The instructions that the rendered view shows. */
  preview: string;
  mode: InstructionsDisplayMode;
  onModeChange: (mode: InstructionsDisplayMode) => void;
  busy: boolean;
  onAdd: (upload: PreparedSkillFilesUpload) => void;
  onRemove: (path: string) => void;
  onPreparingChange: (preparing: boolean) => void;
  /** What happens to an added file, shown in place of its contents. */
  addedFileNote: string | RichStr;
}

/** The files of a skill beside a viewer of the selected file. While editing,
 * SKILL.md is a text field and files can be added or removed. */
export default function SkillBundleEditor({
  files,
  editing,
  text,
  onTextChange,
  preview,
  mode,
  onModeChange,
  busy,
  onAdd,
  onRemove,
  onPreparingChange,
  addedFileNote,
}: SkillBundleEditorProps) {
  const t = useTranslations("customize.skillPage.contents");
  const [selected, setSelected] = useState(SKILL_MD);
  const listed = files.filter((file) => file.path !== SKILL_MD);
  const shown =
    selected === SKILL_MD || listed.some((file) => file.path === selected)
      ? selected
      : SKILL_MD;
  const selectedFile = listed.find((file) => file.path === shown);

  return (
    <SplitCard
      minHeight={32}
      aside={
        <>
          <Section gap={0.25} alignItems="stretch" height="auto">
            {[{ path: SKILL_MD, size: null, added: false }, ...listed].map(
              (file) => (
                <LineItemButton
                  key={file.path}
                  icon={SvgFileText}
                  title={file.path}
                  titleMaxLines={1}
                  state={file.path === shown ? "selected" : "empty"}
                  selectVariant="select-heavy"
                  onClick={() => setSelected(file.path)}
                />
              )
            )}
          </Section>
          {editing && (
            <SkillFilesPicker
              icon={SvgPlus}
              label={t("addFile")}
              disabled={busy}
              onChange={onAdd}
              onPreparingChange={onPreparingChange}
              onError={(message) => toast.error(message)}
            />
          )}
        </>
      }
    >
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="center"
        height="auto"
        gap={1}
      >
        <Text as="p" font="secondary-mono" color="text-03" maxLines={1}>
          {`/${shown}`}
        </Text>
        {shown === SKILL_MD ? (
          <InstructionsDisplayModeToggle value={mode} onChange={onModeChange} />
        ) : (
          editing &&
          selectedFile && (
            <Button
              prominence="tertiary"
              icon={SvgTrash}
              disabled={busy}
              aria-label={t("removeFile", { name: shown })}
              tooltip={t("removeFile", { name: shown })}
              onClick={() => onRemove(selectedFile.path)}
            />
          )
        )}
      </Section>
      {shown !== SKILL_MD ? (
        <Text as="p" font="secondary-body" color="text-03">
          {selectedFile?.added ? addedFileNote : t("noPreview")}
        </Text>
      ) : mode === "raw" ? (
        <InputTextArea
          aria-label={t("editorLabel")}
          mono
          rows={18}
          value={text}
          onChange={(event) => onTextChange(event.target.value)}
          variant={!editing ? "readOnly" : busy ? "disabled" : "internal"}
        />
      ) : (
        <CompactMarkdown>{preview}</CompactMarkdown>
      )}
    </SplitCard>
  );
}
