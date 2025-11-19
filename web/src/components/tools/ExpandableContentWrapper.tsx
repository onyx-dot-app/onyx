// ExpandableContentWrapper
import React, { useState, useEffect } from "react";
import {
  CustomTooltip,
  TooltipGroup,
} from "@/components/tooltip/CustomTooltip";
import {
  DexpandTwoIcon,
  DownloadCSVIcon,
  ExpandTwoIcon,
  OpenIcon,
} from "@/components/icons/icons";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Modal } from "@/components/Modal";
import { FileDescriptor } from "@/app/chat/interfaces";

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
      className={`${
        !expanded ? "w-message-sm" : "w-full"
      } !rounded !rounded-lg overflow-y-hidden h-full`}
    >
      <CardHeader className="w-full py-4 bg-background-tint-02 top-0">
        <div className="flex justify-between items-center">
          <CardTitle className="text-ellipsis line-clamp-1 text-xl font-semibold text-text-700 pr-4">
            {fileDescriptor.name || "Untitled"}
          </CardTitle>
          <div className="flex items-center">
            <TooltipGroup gap="gap-x-4">
              <CustomTooltip showTick line content="Download file">
                <button onClick={downloadFile}>
                  <DownloadCSVIcon className="cursor-pointer hover:text-text-800 h-6 w-6 text-text-400" />
                </button>
              </CustomTooltip>
              <CustomTooltip
                line
                showTick
                content={expanded ? "Minimize" : "Full screen"}
              >
                <button onClick={toggleExpand}>
                  {!expanded ? (
                    <ExpandTwoIcon className="hover:text-text-800 h-6 w-6 cursor-pointer text-text-400" />
                  ) : (
                    <DexpandTwoIcon className="hover:text-text-800 h-6 w-6 cursor-pointer text-text-400" />
                  )}
                </button>
              </CustomTooltip>
              <CustomTooltip showTick line content="Hide">
                <button onClick={close}>
                  <OpenIcon className="hover:text-text-800 h-6 w-6 cursor-pointer text-text-400" />
                </button>
              </CustomTooltip>
            </TooltipGroup>
          </div>
        </div>
      </CardHeader>
      <Card
        className={`!rounded-none p-0 relative mx-auto w-full ${
          expanded ? "max-h-[600px]" : "max-h-[300px] h-full"
        } `}
      >
        <CardContent className="p-0">
          <ContentComponent
            fileDescriptor={fileDescriptor}
            isLoading={isLoading}
            fadeIn={fadeIn}
            expanded={expanded}
          />
        </CardContent>
      </Card>
    </div>
  );

  return (
    <>
      {expanded && (
        <Modal
          hideCloseButton
          onOutsideClick={() => setExpanded(false)}
          className="!max-w-5xl overflow-hidden rounded-lg !p-0 !m-0"
        >
          {Content}
        </Modal>
      )}
      {!expanded && Content}
    </>
  );
}
