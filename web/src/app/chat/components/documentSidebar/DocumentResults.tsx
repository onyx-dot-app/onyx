import { MinimalOnyxDocument, OnyxDocument } from "@/lib/search/interfaces";
import { ChatDocumentDisplay } from "./ChatDocumentDisplay";
import { removeDuplicateDocs } from "@/lib/documentUtils";
import {
  Dispatch,
  ForwardedRef,
  forwardRef,
  SetStateAction,
  useMemo,
  memo,
} from "react";
import { XIcon } from "@/components/icons/icons";
import { getCitations } from "../../services/packetUtils";
import {
  useCurrentMessageTree,
  useSelectedNodeForDocDisplay,
} from "../../stores/useChatSessionStore";

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

interface DocumentResultsProps {
  closeSidebar: () => void;
  selectedDocuments: OnyxDocument[] | null;
  toggleDocumentSelection: (document: OnyxDocument) => void;
  clearSelectedDocuments: () => void;
  selectedDocumentTokens: number;
  maxTokens: number;
  initialWidth: number;
  isOpen: boolean;
  isSharedChat?: boolean;
  modal: boolean;
  setPresentingDocument: Dispatch<SetStateAction<MinimalOnyxDocument | null>>;
}

const DocumentResultsComponent = (
  {
    closeSidebar,
    modal,
    selectedDocuments,
    toggleDocumentSelection,
    clearSelectedDocuments,
    selectedDocumentTokens,
    maxTokens,
    initialWidth,
    isSharedChat,
    isOpen,
    setPresentingDocument,
  }: DocumentResultsProps,
  ref: ForwardedRef<HTMLDivElement>
) => {
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
  if (!selectedMessage || !currentMessageTree) {
    return null;
  }

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

  const tokenLimitReached = selectedDocumentTokens > maxTokens - 75;

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

  const hasDocs = dedupedDocuments.length > 0;
  const hasCited = citedDocuments.length > 0;
  const hasOther = otherDocuments.length > 0;
  const hasHumanFiles = (humanFileDescriptors?.length || 0) > 0;
  const showCloseInUserFiles = !hasCited && !hasOther && hasHumanFiles;

  return (
    <>
      <div
        id="onyx-chat-sidebar"
        className={`relative -mb-8 bg-background max-w-full ${
          !modal
            ? "border-l border-t h-[105vh]  border-sidebar-border dark:border-neutral-700"
            : ""
        }`}
        onClick={(e) => {
          if (e.target === e.currentTarget) {
            closeSidebar();
          }
        }}
      >
        <div
          className={`ml-auto h-full relative sidebar transition-transform ease-in-out duration-300 
            ${isOpen ? " translate-x-0" : " translate-x-[10%]"}`}
          style={{
            width: modal ? undefined : initialWidth,
          }}
        >
          <div className="flex flex-col h-full">
            <div className="overflow-y-auto h-fit mb-8 pb-8 sm:mx-0 flex-grow gap-y-0 default-scrollbar dark-scrollbar flex flex-col">
              {/* Documents Sections */}
              {hasDocs && (
                <>
                  {/* Cited Documents Section */}
                  {hasCited && (
                    <div className="mt-4">
                      <div className="px-4 pb-3 pt-2 flex justify-between border-b border-border">
                        <h3 className="text-base font-semibold text-text-700">
                          Cited Sources
                        </h3>

                        <button
                          aria-label="Close sidebar"
                          title="Close"
                          className="my-auto p-1 rounded transition-colors hover:bg-neutral-200 dark:hover:bg-neutral-700"
                          onClick={closeSidebar}
                        >
                          <XIcon size={16} />
                        </button>
                      </div>
                      {citedDocuments.map((document, ind) => (
                        <div
                          key={document.document_id}
                          className={`desktop:px-2 w-full`}
                        >
                          <ChatDocumentDisplay
                            setPresentingDocument={setPresentingDocument}
                            closeSidebar={closeSidebar}
                            modal={modal}
                            document={document}
                            isSelected={selectedDocumentIds.includes(
                              document.document_id
                            )}
                            handleSelect={(documentId) => {
                              toggleDocumentSelection(
                                dedupedDocuments.find(
                                  (doc) => doc.document_id === documentId
                                )!
                              );
                            }}
                            hideSelection={isSharedChat}
                            tokenLimitReached={tokenLimitReached}
                          />
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Other Documents Section */}
                  {hasOther && (
                    <div className="mt-4">
                      <>
                        <div className="px-4 pb-3 pt-2 border-b border-border">
                          <h3 className="text-base font-semibold text-text-700">
                            {citedDocuments.length > 0
                              ? "More"
                              : "Found Sources"}
                          </h3>
                        </div>
                      </>

                      {otherDocuments.map((document, ind) => (
                        <div
                          key={document.document_id}
                          className={`desktop:px-2 w-full mb-2`}
                        >
                          <ChatDocumentDisplay
                            setPresentingDocument={setPresentingDocument}
                            closeSidebar={closeSidebar}
                            modal={modal}
                            document={document}
                            isSelected={selectedDocumentIds.includes(
                              document.document_id
                            )}
                            handleSelect={(documentId) => {
                              toggleDocumentSelection(
                                dedupedDocuments.find(
                                  (doc) => doc.document_id === documentId
                                )!
                              );
                            }}
                            hideSelection={isSharedChat}
                            tokenLimitReached={tokenLimitReached}
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}

              {/* Human Files Section */}
              {humanFileDescriptors && humanFileDescriptors.length > 0 && (
                <div className="mt-4">
                  <div className="px-4 pb-3 pt-2 flex justify-between border-b border-border">
                    <h3 className="text-base font-semibold text-text-700">
                      User Files
                    </h3>
                    {showCloseInUserFiles && (
                      <button
                        aria-label="Close sidebar"
                        title="Close"
                        className="my-auto p-1 rounded transition-colors hover:bg-neutral-200 dark:hover:bg-neutral-700"
                        onClick={closeSidebar}
                      >
                        <XIcon size={16} />
                      </button>
                    )}
                  </div>
                  {humanFileDescriptors.map((f) => (
                    <div key={f.id} className={`desktop:px-2 w-full mb-2`}>
                      <ChatDocumentDisplay
                        setPresentingDocument={setPresentingDocument}
                        closeSidebar={closeSidebar}
                        modal={modal}
                        document={buildOnyxDocumentFromFile(
                          f.id,
                          f.name,
                          false
                        )}
                        isSelected={false}
                        handleSelect={() => {}}
                        hideSelection={true}
                        tokenLimitReached={false}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
};

export const DocumentResults = memo(forwardRef(DocumentResultsComponent));
DocumentResults.displayName = "DocumentResults";
