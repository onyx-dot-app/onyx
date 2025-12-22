// ExpandableContentWrapper
import React, { useState, useEffect } from "react";
import { SvgDownloadCloud, SvgFold, SvgMaximize2, SvgX } from "@opal/icons";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";
import { FileDescriptor } from "@/app/chat/interfaces";
import { cn } from "@/lib/utils";
import TextView from "@/components/chat/TextView";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";

export interface ExpandableContentWrapperProps {
  fileDescriptor: FileDescriptor;
  close: () => void;
  ContentComponent: React.ComponentType<ContentComponentProps>;
}

export interface ContentComponentProps {
  fileDescriptor: FileDescriptor;
  isLoading: boolean;
  fadeIn: boolean;
  expanded?: boolean;
}

export default function ExpandableContentWrapper({
  fileDescriptor,
  close,
  ContentComponent,
}: ExpandableContentWrapperProps) {
  const [expanded, setExpanded] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [fadeIn, setFadeIn] = useState(false);

  const toggleExpand = () => setExpanded((prev) => !prev);

  // Prevent a jarring fade in
  useEffect(() => {
    setTimeout(() => setIsLoading(false), 300);
  }, []);

  useEffect(() => {
    if (!isLoading) {
      setTimeout(() => setFadeIn(true), 50);
    } else {
      setFadeIn(false);
    }
  }, [isLoading]);

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
    <div
      className={cn(
        !expanded ? "w-message-default" : "w-full",
        "!rounded !rounded-lg overflow-y-hidden h-full"
      )}
    >
      <CardHeader className="w-full bg-background-tint-02 top-0 p-3">
        <div className="flex justify-between items-center">
          <Text
            as="span"
            className="text-ellipsis line-clamp-1"
            text03
            mainUiAction
          >
            {fileDescriptor.name || "Untitled"}
          </Text>
          <div className="flex flex-row items-center justify-end gap-1">
            <IconButton
              internal
              onClick={downloadFile}
              icon={SvgDownloadCloud}
              tooltip="Download file"
            />
            <IconButton
              internal
              onClick={toggleExpand}
              icon={expanded ? SvgFold : SvgMaximize2}
              tooltip={expanded ? "Minimize" : "Full screen"}
            />
            <IconButton internal onClick={close} icon={SvgX} tooltip="Hide" />
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
          {!expanded && (
            <ContentComponent
              fileDescriptor={fileDescriptor}
              isLoading={isLoading}
              fadeIn={fadeIn}
              expanded={expanded}
            />
          )}
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
        <TextView
          presentingDocument={presentingDocument}
          onClose={() => setExpanded(false)}
        />
      )}
      {!expanded && Content}
    </>
  );
}
