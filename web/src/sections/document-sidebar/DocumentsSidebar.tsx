"use client";

import { MinimalOnyxDocument, OnyxDocument } from "@/lib/search/interfaces";
import ChatDocumentDisplay from "@/sections/document-sidebar/ChatDocumentDisplay";
import { removeDuplicateDocs } from "@/lib/documentUtils";
import { Dispatch, SetStateAction, useMemo, memo } from "react";
import { getCitations } from "@/app/chat/services/packetUtils";
import {
  useCurrentMessageTree,
  useSelectedNodeForDocDisplay,
} from "@/app/chat/stores/useChatSessionStore";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgSearchMenu, SvgX } from "@opal/icons";
import Separator from "@/refresh-components/Separator";

// Build an OnyxDocument from basic file info
const buildOnyxDocumentFromFile = (
  id: string,
  name?: string | null,
  appendProjectPrefix?: boolean
): OnyxDocument => {
  const document_id = appendProjectPrefix ? `project_file__${id}` : id;
  return {
    document_id,
    semantic_identifier: name || id,
    link: "",
    source_type: "file" as any,
    blurb: "",
    boost: 0,
    hidden: false,
    score: 1,
    chunk_ind: 0,
    match_highlights: [],
    metadata: {},
    updated_at: null,
    is_internet: false,
  } as any;
};

interface HeaderProps {
  children: string;
  onClose: () => void;
}

function Header({ children, onClose }: HeaderProps) {
  return (
    <div className="sticky top-0 z-sticky bg-background-tint-01">
      <div className="flex flex-row w-full items-center justify-between gap-2 py-3">
        <div className="flex items-center gap-2 w-full px-3">
          <SvgSearchMenu className="w-[1.3rem] h-[1.3rem] stroke-text-03" />
          <Text as="p" headingH3 text03>
            {children}
          </Text>
        </div>
        <IconButton
          icon={SvgX}
          tertiary
          onClick={onClose}
          tooltip="Close Sidebar"
        />
      </div>
      <Separator noPadding />
    </div>
  );
}

interface ChatDocumentDisplayWrapperProps {
  children?: React.ReactNode;
}

function ChatDocumentDisplayWrapper({
  children,
}: ChatDocumentDisplayWrapperProps) {
  return (
    <div className="flex flex-col gap-1 items-center justify-center">
      {children}
    </div>
  );
}

interface DocumentsSidebarProps {
  closeSidebar: () => void;
  selectedDocuments: OnyxDocument[] | null;
  modal: boolean;
  setPresentingDocument: Dispatch<SetStateAction<MinimalOnyxDocument | null>>;
}

const DocumentsSidebar = memo(
  ({
    closeSidebar,
    modal,
    selectedDocuments,
    setPresentingDocument,
  }: DocumentsSidebarProps) => {
    const idOfMessageToDisplay = useSelectedNodeForDocDisplay();
    const currentMessageTree = useCurrentMessageTree();

    const selectedMessage = idOfMessageToDisplay
      ? currentMessageTree?.get(idOfMessageToDisplay)
      : null;

    // Separate cited documents from other documents
    const citedDocumentIds = useMemo(() => {
      if (!selectedMessage) {
        return new Set<string>();
      }

      const citedDocumentIds = new Set<string>();
      const citations = getCitations(selectedMessage.packets);
      citations.forEach((citation) => {
        citedDocumentIds.add(citation.document_id);
      });
      return citedDocumentIds;
    }, [idOfMessageToDisplay, selectedMessage?.packets.length]);

    // if these are missing for some reason, then nothing we can do. Just
    // don't render.
    // TODO: improve this display
    if (!selectedMessage || !currentMessageTree) return null;

    const humanMessage = selectedMessage.parentNodeId
      ? currentMessageTree.get(selectedMessage.parentNodeId)
      : null;
    const humanFileDescriptors = humanMessage?.files.filter(
      (file) => file.user_file_id !== null
    );
    const selectedDocumentIds =
      selectedDocuments?.map((document) => document.document_id) || [];
    const currentDocuments = selectedMessage.documents || null;
    const dedupedDocuments = removeDuplicateDocs(currentDocuments || []);
    const citedDocuments = dedupedDocuments.filter(
      (doc) =>
        doc.document_id !== null &&
        doc.document_id !== undefined &&
        citedDocumentIds.has(doc.document_id)
    );
    const otherDocuments = dedupedDocuments.filter(
      (doc) =>
        doc.document_id === null ||
        doc.document_id === undefined ||
        !citedDocumentIds.has(doc.document_id)
    );
    const hasCited = citedDocuments.length > 0;
    const hasOther = otherDocuments.length > 0;

    return (
      <div
        id="onyx-chat-sidebar"
        className="bg-background-tint-01 overflow-y-scroll h-full w-full border-l"
      >
        <div className="flex flex-col px-3 gap-6">
          {hasCited && (
            <div>
              <Header onClose={closeSidebar}>Cited Sources</Header>
              <ChatDocumentDisplayWrapper>
                {citedDocuments.map((document) => (
                  <ChatDocumentDisplay
                    key={document.document_id}
                    setPresentingDocument={setPresentingDocument}
                    modal={modal}
                    document={document}
                    isSelected={selectedDocumentIds.includes(
                      document.document_id
                    )}
                  />
                ))}
              </ChatDocumentDisplayWrapper>
            </div>
          )}

          {hasOther && (
            <div>
              <Header onClose={closeSidebar}>
                {citedDocuments.length > 0 ? "More" : "Found Sources"}
              </Header>
              <ChatDocumentDisplayWrapper>
                {otherDocuments.map((document) => (
                  <ChatDocumentDisplay
                    key={document.document_id}
                    setPresentingDocument={setPresentingDocument}
                    modal={modal}
                    document={document}
                    isSelected={selectedDocumentIds.includes(
                      document.document_id
                    )}
                  />
                ))}
              </ChatDocumentDisplayWrapper>
            </div>
          )}

          {humanFileDescriptors && humanFileDescriptors.length > 0 && (
            <div>
              <Header onClose={closeSidebar}>User Files</Header>
              <ChatDocumentDisplayWrapper>
                {humanFileDescriptors.map((file) => (
                  <ChatDocumentDisplay
                    key={file.id}
                    setPresentingDocument={setPresentingDocument}
                    modal={modal}
                    document={buildOnyxDocumentFromFile(
                      file.id,
                      file.name,
                      false
                    )}
                    isSelected={false}
                  />
                ))}
              </ChatDocumentDisplayWrapper>
            </div>
          )}
        </div>
      </div>
    );
  }
);
DocumentsSidebar.displayName = "DocumentsSidebar";

export default DocumentsSidebar;
