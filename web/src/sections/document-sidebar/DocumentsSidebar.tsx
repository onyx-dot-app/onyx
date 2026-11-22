"use client";

import { MinimalOnyxDocument, OnyxDocument } from "@/lib/search/types";
import ChatDocumentDisplay from "@/sections/document-sidebar/ChatDocumentDisplay";
import { removeDuplicateDocs } from "@/lib/documentUtils";
import { Dispatch, SetStateAction, useMemo, memo } from "react";
import { useTranslations } from "next-intl";
import { getCitations } from "@/app/app/services/packetUtils";
import {
  useCurrentMessageTree,
  useSelectedNodeForDocDisplay,
} from "@/app/app/stores/useChatSessionStore";
import { Text, Button, Divider } from "@opal/components";
import { SvgSearchMenu, SvgX } from "@opal/icons";
import { cn } from "@opal/utils";

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
  };
};

interface HeaderProps {
  children: string;
  // Without one, the header has no close button: its panel closes itself
  onClose?: () => void;
}

function Header({ children, onClose }: HeaderProps) {
  const t = useTranslations("chat.documentSidebar");

  return (
    <div
      className={cn(
        "sticky top-0 z-sticky",
        onClose ? "bg-background-tint-01" : "bg-background-neutral-00"
      )}
    >
      <div className="flex flex-row w-full items-center justify-between gap-2 py-3">
        <div className="flex items-center gap-2 w-full px-3">
          <SvgSearchMenu className="w-[1.3rem] h-[1.3rem] stroke-text-03" />
          <Text as="p" font="heading-section" color="text-03">
            {children}
          </Text>
        </div>
        {onClose && (
          <Button
            icon={SvgX}
            prominence="tertiary"
            onClick={onClose}
            tooltip={t("closeButton.tooltip")}
          />
        )}
      </div>
      <Divider paddingParallel={0} paddingPerpendicular={0} />
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
  // Without it, the sidebar sits in a panel that draws its own frame and
  // close button: it has no close button, border or background of its own
  closeSidebar?: () => void;
  selectedDocuments: OnyxDocument[] | null;
  setPresentingDocument: Dispatch<SetStateAction<MinimalOnyxDocument | null>>;
}

const DocumentsSidebar = memo(
  ({
    closeSidebar,
    selectedDocuments,
    setPresentingDocument,
  }: DocumentsSidebarProps) => {
    const t = useTranslations("chat.documentSidebar");
    const idOfMessageToDisplay = useSelectedNodeForDocDisplay();
    const currentMessageTree = useCurrentMessageTree();

    const selectedMessage = idOfMessageToDisplay
      ? currentMessageTree?.get(idOfMessageToDisplay)
      : null;

    // Get citations in order and build a set of cited document IDs
    const { citedDocumentIds, citationOrder } = useMemo(() => {
      if (!selectedMessage) {
        return {
          citedDocumentIds: new Set<string>(),
          citationOrder: new Map<string, number>(),
        };
      }

      const citedDocumentIds = new Set<string>();
      const citationOrder = new Map<string, number>();
      const citations = getCitations(selectedMessage.packets);
      citations.forEach((citation, index) => {
        citedDocumentIds.add(citation.document_id);
        // Only set the order for the first occurrence
        if (!citationOrder.has(citation.document_id)) {
          citationOrder.set(citation.document_id, index);
        }
      });
      return { citedDocumentIds, citationOrder };
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
    const citedDocuments = dedupedDocuments
      .filter(
        (doc) =>
          doc.document_id !== null &&
          doc.document_id !== undefined &&
          citedDocumentIds.has(doc.document_id)
      )
      .sort((a, b) => {
        // Sort by citation order (order citations appeared in the answer)
        const orderA = citationOrder.get(a.document_id) ?? Infinity;
        const orderB = citationOrder.get(b.document_id) ?? Infinity;
        return orderA - orderB;
      });
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
        className={cn(
          "overflow-y-scroll h-full w-full",
          closeSidebar && "bg-background-tint-01 border-s"
        )}
      >
        <div className="flex flex-col px-3 gap-6">
          {hasCited && (
            <div>
              <Header onClose={closeSidebar}>{t("citedSources.title")}</Header>
              <ChatDocumentDisplayWrapper>
                {citedDocuments.map((document) => (
                  <ChatDocumentDisplay
                    key={document.document_id}
                    setPresentingDocument={setPresentingDocument}
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
                {citedDocuments.length > 0
                  ? t("moreSources.title")
                  : t("foundSources.title")}
              </Header>
              <ChatDocumentDisplayWrapper>
                {otherDocuments.map((document) => (
                  <ChatDocumentDisplay
                    key={document.document_id}
                    setPresentingDocument={setPresentingDocument}
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
              <Header onClose={closeSidebar}>{t("userFiles.title")}</Header>
              <ChatDocumentDisplayWrapper>
                {humanFileDescriptors.map((file) => (
                  <ChatDocumentDisplay
                    key={file.id}
                    setPresentingDocument={setPresentingDocument}
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
