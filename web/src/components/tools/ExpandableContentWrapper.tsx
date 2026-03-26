// ExpandableContentWrapper
import React, { useState } from "react";
import { SvgDownloadCloud, SvgFold, SvgMaximize2, SvgX } from "@opal/icons";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@opal/components";
// TODO(@raunakab): migrate this `refresh-components/Text` to `@opal/components` Text
import Text from "@/refresh-components/texts/Text";
import { FileDescriptor } from "@/app/app/interfaces";
import { cn } from "@/lib/utils";
import PreviewModal from "@/sections/modals/PreviewModal";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";

export interface ExpandableContentWrapperProps {
  fileDescriptor: FileDescriptor;
  close: () => void;
  ContentComponent: React.ComponentType<ContentComponentProps>;
}

export interface ContentComponentProps {
  fileDescriptor: FileDescriptor;
  expanded?: boolean;
}

export default function ExpandableContentWrapper({
  fileDescriptor,
  close,
  ContentComponent,
}: ExpandableContentWrapperProps) {
  const [expanded, setExpanded] = useState(false);

  const toggleExpand = () => setExpanded((prev) => !prev);

  const downloadFile = () => {
    const a = document.createElement("a");
    a.href = `api/chat/file/${fileDescriptor.id}`;
    a.download = fileDescriptor.name || "download.csv";
    a.setAttribute("download", fileDescriptor.name || "download.csv");
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const Content = (
    <div className="w-message-default max-w-full !rounded-lg overflow-y-hidden h-full">
      <CardHeader className="w-full bg-background-tint-02 top-0 p-3">
        <div className="flex justify-between items-center">
          <Text className="text-ellipsis line-clamp-1" text03 mainUiAction>
            {fileDescriptor.name || "Untitled"}
          </Text>
          <div className="flex flex-row items-center justify-end gap-1">
            <Button
              prominence="tertiary"
              size="sm"
              onClick={downloadFile}
              icon={SvgDownloadCloud}
              tooltip="Download file"
            />
            <Button
              prominence="tertiary"
              size="sm"
              onClick={toggleExpand}
              icon={expanded ? SvgFold : SvgMaximize2}
              tooltip={expanded ? "Minimize" : "Full screen"}
            />
            <Button
              prominence="tertiary"
              size="sm"
              onClick={close}
              icon={SvgX}
              tooltip="Hide"
            />
          </div>
        </div>
      </CardHeader>
      <Card
        className={cn(
          "!rounded-none p-0 relative mx-auto w-full",
          expanded ? "max-h-[600px]" : "max-h-[300px] h-full"
        )}
      >
        <CardContent className="p-0">
          <ContentComponent
            fileDescriptor={fileDescriptor}
            expanded={expanded}
          />
        </CardContent>
      </Card>
    </div>
  );

  const presentingDocument: MinimalOnyxDocument = {
    document_id: fileDescriptor.id,
    semantic_identifier: fileDescriptor.name ?? null,
  };

  return (
    <>
      {expanded && (
        <PreviewModal
          presentingDocument={presentingDocument}
          onClose={() => setExpanded(false)}
        />
      )}
      {!expanded && Content}
    </>
  );
}
