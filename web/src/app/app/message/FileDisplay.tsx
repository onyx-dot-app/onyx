"use client";

import { ReactNode, useState } from "react";
import { cn } from "@/lib/utils";
import { ChatFileType, FileDescriptor } from "@/app/app/interfaces";
import Attachment from "@/refresh-components/Attachment";
import { InMessageImage } from "@/app/app/components/files/images/InMessageImage";
import CsvContent from "@/components/tools/CSVContent";
import PreviewModal from "@/sections/modals/PreviewModal";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
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
  const textFiles = files.filter(
    (file) =>
      file.type === ChatFileType.PLAIN_TEXT ||
      file.type === ChatFileType.DOCUMENT ||
      file.type === ChatFileType.TABULAR
  );
  const imageFiles = files.filter((file) => file.type === ChatFileType.IMAGE);
  const csvFiles = files.filter((file) => file.type === ChatFileType.CSV);

  const presentingDocument: MinimalOnyxDocument = {
    document_id: previewingFile?.id ?? "",
    semantic_identifier: previewingFile?.name ?? "",
  };

  return (
    <>
      {previewingFile && (
        <PreviewModal
          presentingDocument={presentingDocument}
          onClose={() => setPreviewingFile(null)}
        />
      )}

      {textFiles.length > 0 && (
        <FileContainer id="onyx-file">
          {textFiles.map((file) => (
            <Attachment
              key={file.id}
              fileName={file.name || file.id}
              open={() => setPreviewingFile(file)}
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

      {csvFiles.length > 0 && (
        <FileContainer className="overflow-auto">
          {csvFiles.map((file) =>
            close ? (
              <ExpandableContentWrapper
                key={file.id}
                fileDescriptor={file}
                close={() => setClose(false)}
                ContentComponent={CsvContent}
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
