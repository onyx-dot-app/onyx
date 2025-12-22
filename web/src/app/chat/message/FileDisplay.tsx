"use client";

import { useState } from "react";
import { ChatFileType, FileDescriptor } from "@/app/chat/interfaces";
import Attachment from "@/refresh-components/Attachment";
import { InMessageImage } from "@/app/chat/components/files/images/InMessageImage";
import CsvContent from "@/components/tools/CSVContent";
import TextView from "@/components/chat/TextView";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { cn } from "@/lib/utils";
import ExpandableContentWrapper from "@/components/tools/ExpandableContentWrapper";

interface FileDisplayProps {
  files: FileDescriptor[];
  alignBubble?: boolean;
}

export default function FileDisplay({ files, alignBubble }: FileDisplayProps) {
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
        <TextView
          presentingDocument={presentingDocument}
          onClose={() => setPreviewingFile(null)}
        />
      )}

      {textFiles.length > 0 && (
        <div
          id="onyx-file"
          className={cn("m-2 auto", alignBubble && "ml-auto")}
        >
          <div className="flex flex-col items-end gap-2">
            {textFiles.map((file) => (
              <Attachment
                key={file.id}
                fileName={file.name || file.id}
                open={() => setPreviewingFile(file)}
              />
            ))}
          </div>
        </div>
      )}

      {imageFiles.length > 0 && (
        <div
          id="onyx-image"
          className={cn("m-2 auto", alignBubble && "ml-auto")}
        >
          <div className="flex flex-col items-end gap-2">
            {imageFiles.map((file) => (
              <InMessageImage key={file.id} fileId={file.id} />
            ))}
          </div>
        </div>
      )}

      {csvFiles.length > 0 && (
        <div className={cn("m-2 auto", alignBubble && "ml-auto")}>
          <div className="flex flex-col items-end gap-2">
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
        </div>
      )}
    </>
  );
}
