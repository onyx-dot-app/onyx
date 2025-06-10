import { MinimalOnyxDocument, OnyxDocument } from "@/lib/search/interfaces";
import { ChatDocumentDisplay } from "./ChatDocumentDisplay";
import { removeDuplicateDocs } from "@/lib/documentUtils";
import { ChatFileType, Message } from "../interfaces";
import {
  Dispatch,
  ForwardedRef,
  forwardRef,
  SetStateAction,
  useEffect,
  useState,
} from "react";
import { XIcon } from "@/components/icons/icons";
import { FileSourceCardInResults } from "../message/SourcesDisplay";
import { useDocumentsContext } from "../my-documents/DocumentsContext";
interface DocumentResultsProps {
  agenticMessage: boolean;
  humanMessage: Message | null;
  closeSidebar: () => void;
  selectedMessage: Message | null;
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
  removeHeader?: boolean;
}

export const DocumentResults = forwardRef<HTMLDivElement, DocumentResultsProps>(
  (
    {
      agenticMessage,
      humanMessage,
      closeSidebar,
      modal,
      selectedMessage,
      selectedDocuments,
      toggleDocumentSelection,
      clearSelectedDocuments,
      selectedDocumentTokens,
      maxTokens,
      initialWidth,
      isSharedChat,
      isOpen,
      setPresentingDocument,
      removeHeader,
    },
    ref: ForwardedRef<HTMLDivElement>
  ) => {
    const [delayedSelectedDocumentCount, setDelayedSelectedDocumentCount] =
      useState(0);

    useEffect(() => {
      const timer = setTimeout(
        () => {
          setDelayedSelectedDocumentCount(selectedDocuments?.length || 0);
        },
        selectedDocuments?.length == 0 ? 1000 : 0
      );

      return () => clearTimeout(timer);
    }, [selectedDocuments]);
    const { files: allUserFiles } = useDocumentsContext();

    const humanFileDescriptors = humanMessage?.files.filter(
      (file) => file.type == ChatFileType.USER_KNOWLEDGE
    );
    const userFiles = allUserFiles?.filter((file) =>
      humanFileDescriptors?.some((descriptor) => descriptor.id === file.file_id)
    );
    const selectedDocumentIds =
      selectedDocuments?.map((document) => document.document_id) || [];

    const currentDocuments = selectedMessage?.documents || null;
    const dedupedDocuments = removeDuplicateDocs(currentDocuments || []);

    const tokenLimitReached = selectedDocumentTokens > maxTokens - 75;

    const hasSelectedDocuments = selectedDocumentIds.length > 0;
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
              {!removeHeader && (
                <>
                  <div className="p-4 flex items-center justify-between gap-x-2">
                    <div className="flex items-center gap-x-2">
                      <h2 className="text-xl font-bold text-text-900">
                        Sources
                      </h2>
                    </div>
                    <button className="my-auto" onClick={closeSidebar}>
                      <XIcon size={16} />
                    </button>
                  </div>
                  <div className="border-b border-divider-history-sidebar-bar mx-3" />
                </>
              )}

              <div className="overflow-y-auto h-fit mb-8 pb-8 sm:mx-0 flex-grow gap-y-0 default-scrollbar dark-scrollbar flex flex-col">
                {userFiles && userFiles.length > 0 ? (
                  <div className=" gap-y-2 flex flex-col pt-2 mx-3">
                    {userFiles?.map((file, index) => (
                      <FileSourceCardInResults
                        key={index}
                        relevantDocument={dedupedDocuments.find(
                          (doc) =>
                            doc.document_id ===
                            `FILE_CONNECTOR__${file.file_id}`
                        )}
                        document={file}
                        setPresentingDocument={() =>
                          setPresentingDocument({
                            document_id: file.document_id,
                            semantic_identifier: file.file_id || null,
                          })
                        }
                      />
                    ))}
                  </div>
                ) : dedupedDocuments.length > 0 ? (
                  dedupedDocuments.map((document, ind) => (
                    <div
                      key={document.document_id}
                      className={`desktop:px-2 w-full`}
                    >
                      <ChatDocumentDisplay
                        agenticMessage={agenticMessage}
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
                  ))
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </>
    );
  }
);

DocumentResults.displayName = "DocumentResults";
