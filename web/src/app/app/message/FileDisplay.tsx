"use client";

import { useState } from "react";
import { ChatFileType, FileDescriptor } from "@/app/app/interfaces";
import Attachment from "@/refresh-components/Attachment";
import { InMessageImage } from "@/app/app/components/files/images/InMessageImage";
import CsvContent from "@/components/tools/CSVContent";
import TextViewModal from "@/sections/modals/TextViewModal";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import ExpandableContentWrapper from "@/components/tools/ExpandableContentWrapper";

interface FileDisplayProps {
  files: FileDescriptor[];
}

export default function FileDisplay({ files }: FileDisplayProps) {
  const [close, setClose] = useState(true);
  const [previewingFile, setPreviewingFile] = useState<FileDescriptor | null>(
    null
  );
  const textFiles = files.filter(
    (file) =>
      file.type === ChatFileType.PLAIN_TEXT ||
      file.type === ChatFileType.DOCUMENT
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
        <TextViewModal
          presentingDocument={presentingDocument}
          onClose={() => setPreviewingFile(null)}
        />
      )}

      {textFiles.length > 0 && (
        <div id="onyx-file" className="flex flex-col items-end gap-2 py-2">
          {textFiles.map((file) => (
            <Attachment
              key={file.id}
              fileName={file.name || file.id}
              open={() => setPreviewingFile(file)}
            />
          ))}
        </div>
      )}

      {imageFiles.length > 0 && (
        <div id="onyx-image" className="flex flex-col items-end gap-2 py-2">
          {imageFiles.map((file) => (
            <InMessageImage key={file.id} fileId={file.id} />
          ))}
        </div>
      )}

      {csvFiles.length > 0 && (
        <div className="flex flex-col items-end gap-2 py-2">
          {csvFiles.map((file) => {
            return (
              <div key={file.id} className="w-fit">
                {close ? (
                  <>
                    <ExpandableContentWrapper
                      fileDescriptor={file}
                      close={() => setClose(false)}
                      ContentComponent={CsvContent}
                    />
                  </>
                ) : (
                  <Attachment
                    open={() => setClose(true)}
                    fileName={file.name || file.id}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
