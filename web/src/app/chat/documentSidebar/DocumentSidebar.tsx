import { DanswerDocument } from "@/lib/search/interfaces";
import { Text } from "@tremor/react";
import { ChatDocumentDisplay } from "./ChatDocumentDisplay";
import { usePopup } from "@/components/admin/connectors/Popup";
import { FiAlertTriangle, FiFileText } from "react-icons/fi";
import { SelectedDocumentDisplay } from "./SelectedDocumentDisplay";
import { removeDuplicateDocs } from "@/lib/documentUtils";
import { BasicSelectable } from "@/components/BasicClickable";
import { Message, RetrievalType } from "../interfaces";
import { HEADER_PADDING } from "@/lib/constants";
import { HoverPopup } from "@/components/HoverPopup";

function SectionHeader({
  name,
  icon,
}: {
  name: string;
  icon: React.FC<{ className: string }>;
}) {
  return (
    <div className="text-lg text-emphasis font-medium flex pb-0.5 mb-3.5 mt-2 font-bold">
      {icon({ className: "my-auto mr-1" })}
      {name}
    </div>
  );
}

export function DocumentSidebar({
  selectedMessage,
  selectedDocuments,
  toggleDocumentSelection,
  clearSelectedDocuments,
  selectedDocumentTokens,
  maxTokens,
  isLoading,
}: {
  selectedMessage: Message | null;
  selectedDocuments: DanswerDocument[] | null;
  toggleDocumentSelection: (document: DanswerDocument) => void;
  clearSelectedDocuments: () => void;
  selectedDocumentTokens: number;
  maxTokens: number;
  isLoading: boolean;
}) {
  const { popup, setPopup } = usePopup();

  const selectedMessageRetrievalType = selectedMessage?.retrievalType || null;

  const selectedDocumentIds =
    selectedDocuments?.map((document) => document.document_id) || [];

  const currentDocuments = selectedMessage?.documents || null;
  const dedupedDocuments = removeDuplicateDocs(currentDocuments || []);

  // NOTE: do not allow selection if less than 75 tokens are left
  // this is to prevent the case where they are able to select the doc
  // but it basically is unused since it's truncated right at the very
  // start of the document (since title + metadata + misc overhead) takes up
  // space
  const tokenLimitReached = selectedDocumentTokens > maxTokens - 75;
  return (
    <div
      className={`
      flex-initial 
      overflow-y-hidden
      flex
      flex-col
      w-full
      h-screen
      `}
      id="document-sidebar"
    >
      {popup}

      <div className="h-4/6 flex flex-col mt-4">
        <div className="px-3 mb-3 flex border-b border-border">
          <SectionHeader
            name={
              selectedMessageRetrievalType === RetrievalType.SelectedDocs
                ? "Referenced Documents"
                : "Retrieved Documents"
            }
            icon={FiFileText}
          />
        </div>

        {currentDocuments ? (
          <div className="overflow-y-auto dark-scrollbar flex flex-col">
            <div>
              {dedupedDocuments.length > 0 ? (
                dedupedDocuments.map((document, ind) => (
                  <div
                    key={document.document_id}
                    className={
                      ind === dedupedDocuments.length - 1
                        ? "mb-5"
                        : "border-b border-border-light mb-3"
                    }
                  >
                    <ChatDocumentDisplay
                      document={document}
                      setPopup={setPopup}
                      queryEventId={null}
                      isAIPick={false}
                      isSelected={selectedDocumentIds.includes(
                        document.document_id
                      )}
                      handleSelect={(documentId) => {
                        toggleDocumentSelection(
                          dedupedDocuments.find(
                            (document) => document.document_id === documentId
                          )!
                        );
                      }}
                      tokenLimitReached={tokenLimitReached}
                    />
                  </div>
                ))
              ) : (
                <div className="mx-3">
                  <Text>No documents found for the query.</Text>
                </div>
              )}
            </div>
          </div>
        ) : (
          !isLoading && (
            <div className="ml-4 mr-3">
              <Text>
                When you run ask a question, the retrieved documents will show
                up here!
              </Text>
            </div>
          )
        )}
      </div>

      <div className="text-sm mb-4 border-t border-border pt-4 overflow-y-hidden flex flex-col">
        <div className="flex border-b border-border px-3">
          <div className="flex">
            <SectionHeader name="Selected Documents" icon={FiFileText} />

            {tokenLimitReached && (
              <div className="ml-2 my-auto">
                <div className="mb-2">
                  <HoverPopup
                    mainContent={
                      <FiAlertTriangle
                        className="text-alert my-auto"
                        size="16"
                      />
                    }
                    popupContent={
                      <Text className="w-40">
                        Over LLM context length by:{" "}
                        <i>{selectedDocumentTokens - maxTokens} tokens</i>
                        <br />
                        <br />
                        {selectedDocuments && selectedDocuments.length > 0 && (
                          <>
                            Truncating: &quot;
                            <i>
                              {
                                selectedDocuments[selectedDocuments.length - 1]
                                  .semantic_identifier
                              }
                            </i>
                            &quot;
                          </>
                        )}
                      </Text>
                    }
                    direction="left"
                  />
                </div>
              </div>
            )}
          </div>

          {selectedDocuments && selectedDocuments.length > 0 && (
            <div className="ml-auto my-auto" onClick={clearSelectedDocuments}>
              <BasicSelectable selected={false}>De-Select All</BasicSelectable>
            </div>
          )}
        </div>

        {selectedDocuments && selectedDocuments.length > 0 ? (
          <div className="flex flex-col gap-y-2 py-3 px-3 overflow-y-auto dark-scrollbar max-h-full">
            {selectedDocuments.map((document) => (
              <SelectedDocumentDisplay
                key={document.document_id}
                document={document}
                handleDeselect={(documentId) => {
                  toggleDocumentSelection(
                    dedupedDocuments.find(
                      (document) => document.document_id === documentId
                    )!
                  );
                }}
              />
            ))}
          </div>
        ) : (
          !isLoading && (
            <Text className="mx-3 py-3">
              Select documents from the retrieved documents section to chat
              specifically with them!
            </Text>
          )
        )}
      </div>
    </div>
  );
}
