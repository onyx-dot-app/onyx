"use client";

import { useRef, useState, type ChangeEvent } from "react";
import { useField } from "formik";
import { useTranslations } from "next-intl";
import { Button, Card, Text } from "@opal/components";
import { Content, ContentAction, Section, toast } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgFile, SvgUploadCloud, SvgX } from "@opal/icons";
import * as TableLayouts from "@/layouts/table-layouts";
import {
  storedFileList,
  withoutFile,
  withStagedFiles,
  type ConnectorFileList,
} from "@/lib/connectors/edit/files";
import { stageEditFiles } from "@/lib/connectors/edit/svc";

export interface EditFileLocationsProps {
  ccPairId: number;
  /** Told when an upload starts and ends, so the page can wait for it. */
  onUploadingChange?: (uploading: boolean) => void;
}

/**
 * The file list of a file connector in edit mode. It edits the config's
 * `file_locations`, `file_names` and `zip_metadata_file_id`. Uploads are
 * staged for the edit; only an applied plan indexes them.
 */
export default function EditFileLocations({
  ccPairId,
  onUploadingChange,
}: EditFileLocationsProps) {
  const t = useTranslations("admin.connectorEdit.files");
  const [locations, , locationsHelpers] = useField<string[] | undefined>(
    "file_locations"
  );
  const [names, , namesHelpers] = useField<string[] | null | undefined>(
    "file_names"
  );
  const [zipMetadata, , zipMetadataHelpers] = useField<
    string | null | undefined
  >("zip_metadata_file_id");
  const [uploading, setUploadingState] = useState(false);
  const setUploading = (next: boolean) => {
    setUploadingState(next);
    onUploadingChange?.(next);
  };
  const inputRef = useRef<HTMLInputElement>(null);

  const list = storedFileList(locations.value ?? [], names.value ?? null);

  const setList = (next: ConnectorFileList) => {
    void locationsHelpers.setValue(next.fileIds);
    void namesHelpers.setValue(next.fileNames);
  };

  const upload = async (files: File[]) => {
    setUploading(true);
    try {
      // The edit's metadata file id, so a second zip merges into the first.
      const staged = await stageEditFiles(
        ccPairId,
        files,
        zipMetadata.value ?? null
      );
      setList(withStagedFiles(list, staged));
      void zipMetadataHelpers.setValue(staged.zip_metadata_file_id);
    } catch (error) {
      toast.error(
        t("uploadFailed.toast", {
          detail: error instanceof Error ? error.message : "",
        })
      );
    } finally {
      setUploading(false);
    }
  };

  const onFilesPicked = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (files.length > 0) void upload(files);
  };

  return (
    <Section gap={2} alignItems="stretch" height="fit">
      <Content
        title={t("title")}
        description={t("description")}
        sizePreset="main-ui"
        variant="section"
      />
      {list.fileIds.length === 0 ? (
        <Text font="secondary-body" color="text-03">
          {t("empty")}
        </Text>
      ) : (
        list.fileIds.map((fileId, index) => {
          const name = list.fileNames[index] ?? fileId;
          return (
            <Card key={fileId} color="background-tint-01" padding={2}>
              <ContentAction
                icon={SvgFile}
                title={name}
                sizePreset="main-ui"
                variant="section"
                rightChildren={
                  <Button
                    icon={SvgX}
                    prominence="tertiary"
                    disabled={uploading}
                    tooltip={t("remove.tooltip", { name })}
                    aria-label={t("remove.tooltip", { name })}
                    onClick={() => setList(withoutFile(list, fileId))}
                  />
                }
              />
            </Card>
          );
        })
      )}
      <TableLayouts.HiddenInput
        inputRef={inputRef}
        type="file"
        multiple
        data-testid="edit-file-input"
        onChange={onFilesPicked}
      />
      <Section flexDirection="row" justifyContent="start" height="fit">
        <Button
          prominence="secondary"
          icon={uploading ? IconLoader : SvgUploadCloud}
          disabled={uploading}
          onClick={() => inputRef.current?.click()}
        >
          {t("addButton.label")}
        </Button>
      </Section>
    </Section>
  );
}
