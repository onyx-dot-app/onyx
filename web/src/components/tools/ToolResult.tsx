import React from "react";
import ExpandableContentWrapper, {
  ContentComponentProps,
} from "./ExpandableContentWrapper";
import { FileDescriptor } from "@/app/chat/interfaces";

interface ToolResultProps {
  csvFileDescriptor: FileDescriptor;
  close: () => void;
  contentComponent: React.ComponentType<ContentComponentProps>;
}

const ToolResult: React.FC<ToolResultProps> = ({
  csvFileDescriptor,
  close,
  contentComponent,
}) => {
  return (
    <ExpandableContentWrapper
      fileDescriptor={csvFileDescriptor}
      close={close}
      ContentComponent={contentComponent}
    />
  );
};

export default ToolResult;
