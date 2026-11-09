"use client";

import { ReactNode, useMemo, useState } from "react";
import { cn } from "@opal/utils";
import { useCreateModal } from "@opal/components";
import { ChatFileType, FileDescriptor } from "@/app/app/types";
import Attachment from "@/refresh-components/Attachment";
import { InMessageImage } from "@/app/app/components/files/images/InMessageImage";
import SpreadsheetContent from "@/components/tools/SpreadsheetContent";
import PreviewModal from "@/sections/modals/PreviewModal";
import { MinimalOnyxDocument } from "@/lib/search/types";
import ExpandableContentWrapper from "@/components/tools/ExpandableContentWrapper";

interface FileContainerProps {
  children: ReactNode;
  className?: string;
  id?: string;
}

interface FileDisplayProps {
  files: FileDescriptor[];
}

function FileContainer({ children, className, id }: FileContainerProps) {
  return (
    <div
      id={id}
      className={cn("flex w-full flex-col items-end gap-2 py-2", className)}
    >
      {children}
    </div>
  );
}

export default function FileDisplay({ files }: FileDisplayProps) {
  const [close, setClose] = useState(true);
  const [previewingFile, setPreviewingFile] = useState<FileDescriptor | null>(
    null
  );
  const previewModal = useCreateModal();
  const textFiles = files.filter(
    (file) =>
      file.type === ChatFileType.PLAIN_TEXT ||
      file.type === ChatFileType.DOCUMENT
  );
  const imageFiles = files.filter((file) => file.type === ChatFileType.IMAGE);
  const tabularFiles = files.filter(
    (file) => file.type === ChatFileType.TABULAR
  );

  // Stable per file: PreviewModal refetches when this object changes, which
  // would reload the closing card on every rerender.
  const presentingDocument = useMemo<MinimalOnyxDocument>(
    () => ({
      document_id: previewingFile?.id ?? "",
      semantic_identifier: previewingFile?.name ?? "",
    }),
    [previewingFile]
  );

  return (
    <>
      <previewModal.Provider>
        {previewingFile && (
          <PreviewModal
            presentingDocument={presentingDocument}
            onClose={() => previewModal.toggle(false)}
          />
        )}
      </previewModal.Provider>

      {textFiles.length > 0 && (
        <FileContainer id="onyx-file">
          {textFiles.map((file) => (
            <Attachment
              key={file.id}
              fileName={file.name || file.id}
              open={() => {
                setPreviewingFile(file);
                previewModal.toggle(true);
              }}
            />
          ))}
        </FileContainer>
      )}

      {imageFiles.length > 0 && (
        <FileContainer id="onyx-image">
          {imageFiles.map((file) => (
            <InMessageImage key={file.id} fileId={file.id} />
          ))}
        </FileContainer>
      )}

      {tabularFiles.length > 0 && (
        <FileContainer className="overflow-auto">
          {tabularFiles.map((file) =>
            close ? (
              <ExpandableContentWrapper
                key={file.id}
                fileDescriptor={file}
                close={() => setClose(false)}
                // All TABULAR files render via the parsed preview, which
                // dispatches on the response content type: spreadsheet JSON
                // (xlsx is a binary OOXML zip the browser can't decode as
                // text) or raw CSV passthrough. Display names are never
                // trusted — a renamed xlsx/csv still renders correctly.
                ContentComponent={SpreadsheetContent}
              />
            ) : (
              <Attachment
                key={file.id}
                open={() => setClose(true)}
                fileName={file.name || file.id}
              />
            )
          )}
        </FileContainer>
      )}
    </>
  );
}
