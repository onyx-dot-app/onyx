import {
  FiCpu,
  FiImage,
  FiThumbsDown,
  FiThumbsUp,
  FiUser,
  FiEdit2,
  FiChevronRight,
  FiChevronLeft,
} from "react-icons/fi";
import { FeedbackType } from "../types";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { DanswerDocument } from "@/lib/search/interfaces";
import { SearchSummary, ShowHideDocsButton } from "./SearchSummary";
import { SourceIcon } from "@/components/SourceIcon";
import { ThreeDots } from "react-loader-spinner";
import { SkippedSearch } from "./SkippedSearch";
import remarkGfm from "remark-gfm";
import { CopyButton } from "@/components/CopyButton";
import { FileDescriptor } from "../interfaces";
import { InMessageImage } from "../images/InMessageImage";
import { IMAGE_GENERATION_TOOL_NAME } from "../tools/constants";
import { ToolRunningAnimation } from "../tools/ToolRunningAnimation";
import { Hoverable } from "@/components/Hoverable";

const ICON_SIZE = 15;

export const AIMessage = ({
  messageId,
  content,
  files,
  query,
  personaName,
  citedDocuments,
  currentTool,
  isComplete,
  hasDocs,
  handleFeedback,
  isCurrentlyShowingRetrieved,
  handleShowRetrieved,
  handleSearchQueryEdit,
  handleForceSearch,
  retrievalDisabled,
}: {
  messageId: number | null;
  content: string | JSX.Element;
  files?: FileDescriptor[];
  query?: string;
  personaName?: string;
  citedDocuments?: [string, DanswerDocument][] | null;
  currentTool?: string | null;
  isComplete?: boolean;
  hasDocs?: boolean;
  handleFeedback?: (feedbackType: FeedbackType) => void;
  isCurrentlyShowingRetrieved?: boolean;
  handleShowRetrieved?: (messageNumber: number | null) => void;
  handleSearchQueryEdit?: (query: string) => void;
  handleForceSearch?: () => void;
  retrievalDisabled?: boolean;
}) => {
  const loader =
    currentTool === IMAGE_GENERATION_TOOL_NAME ? (
      <div className="text-sm my-auto">
        <ToolRunningAnimation
          toolName="Generating images"
          toolLogo={<FiImage size={16} className="my-auto mr-1" />}
        />
      </div>
    ) : (
      <div className="text-sm my-auto">
        <ThreeDots
          height="30"
          width="50"
          color="#3b82f6"
          ariaLabel="grid-loading"
          radius="12.5"
          wrapperStyle={{}}
          wrapperClass=""
          visible={true}
        />
      </div>
    );

  return (
    <div className={"py-5 px-5 flex -mr-6 w-full"}>
      <div className="mx-auto w-searchbar-xs 2xl:w-searchbar-sm 3xl:w-searchbar relative">
        <div className="ml-8">
          <div className="flex">
            <div className="p-1 bg-ai rounded-lg h-fit my-auto">
              <div className="text-inverted">
                <FiCpu size={16} className="my-auto mx-auto" />
              </div>
            </div>

            <div className="font-bold text-emphasis ml-2 my-auto">
              {personaName || "Danswer"}
            </div>

            {query === undefined &&
              hasDocs &&
              handleShowRetrieved !== undefined &&
              isCurrentlyShowingRetrieved !== undefined &&
              !retrievalDisabled && (
                <div className="flex w-message-xs 2xl:w-message-sm 3xl:w-message-default absolute ml-8">
                  <div className="ml-auto">
                    <ShowHideDocsButton
                      messageId={messageId}
                      isCurrentlyShowingRetrieved={isCurrentlyShowingRetrieved}
                      handleShowRetrieved={handleShowRetrieved}
                    />
                  </div>
                </div>
              )}
          </div>

          <div className="w-message-xs 2xl:w-message-sm 3xl:w-message-default break-words mt-1 ml-8">
            {query !== undefined &&
              handleShowRetrieved !== undefined &&
              isCurrentlyShowingRetrieved !== undefined &&
              !retrievalDisabled && (
                <div className="my-1">
                  <SearchSummary
                    query={query}
                    hasDocs={hasDocs || false}
                    messageId={messageId}
                    isCurrentlyShowingRetrieved={isCurrentlyShowingRetrieved}
                    handleShowRetrieved={handleShowRetrieved}
                    handleSearchQueryEdit={handleSearchQueryEdit}
                  />
                </div>
              )}
            {handleForceSearch &&
              content &&
              query === undefined &&
              !hasDocs &&
              !retrievalDisabled && (
                <div className="my-1">
                  <SkippedSearch handleForceSearch={handleForceSearch} />
                </div>
              )}

            {content ? (
              <>
                {files && files.length > 0 && (
                  <div className="mt-2 mb-4">
                    <div className="flex flex-wrap gap-2">
                      {files.map((file) => {
                        return (
                          <InMessageImage key={file.id} fileId={file.id} />
                        );
                      })}
                    </div>
                  </div>
                )}
                {typeof content === "string" ? (
                  <ReactMarkdown
                    className="prose max-w-full"
                    components={{
                      a: ({ node, ...props }) => (
                        <a
                          {...props}
                          className="text-blue-500 hover:text-blue-700"
                          target="_blank"
                          rel="noopener noreferrer"
                        />
                      ),
                    }}
                    remarkPlugins={[remarkGfm]}
                  >
                    {content}
                  </ReactMarkdown>
                ) : (
                  content
                )}
              </>
            ) : isComplete ? null : (
              loader
            )}
            {citedDocuments && citedDocuments.length > 0 && (
              <div className="mt-2">
                <b className="text-sm text-emphasis">Sources:</b>
                <div className="flex flex-wrap gap-2">
                  {citedDocuments
                    .filter(([_, document]) => document.semantic_identifier)
                    .map(([citationKey, document], ind) => {
                      const display = (
                        <div className="max-w-350 text-ellipsis flex text-sm border border-border py-1 px-2 rounded flex">
                          <div className="mr-1 my-auto">
                            <SourceIcon
                              sourceType={document.source_type}
                              iconSize={16}
                            />
                          </div>
                          [{citationKey}] {document!.semantic_identifier}
                        </div>
                      );
                      if (document.link) {
                        return (
                          <a
                            key={document.document_id}
                            href={document.link}
                            target="_blank"
                            className="cursor-pointer hover:bg-hover"
                          >
                            {display}
                          </a>
                        );
                      } else {
                        return (
                          <div
                            key={document.document_id}
                            className="cursor-default"
                          >
                            {display}
                          </div>
                        );
                      }
                    })}
                </div>
              </div>
            )}
          </div>
          {handleFeedback && (
            <div className="flex flex-col md:flex-row gap-x-0.5 ml-8 mt-1.5">
              <CopyButton content={content.toString()} />
              <Hoverable
                icon={FiThumbsUp}
                onClick={() => handleFeedback("like")}
              />
              <Hoverable
                icon={FiThumbsDown}
                onClick={() => handleFeedback("dislike")}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

function MessageSwitcher({
  currentPage,
  totalPages,
  handlePrevious,
  handleNext,
}: {
  currentPage: number;
  totalPages: number;
  handlePrevious: () => void;
  handleNext: () => void;
}) {
  return (
    <div className="flex items-center text-sm space-x-0.5">
      <Hoverable
        icon={FiChevronLeft}
        onClick={currentPage === 1 ? undefined : handlePrevious}
      />
      <span className="text-emphasis text-medium select-none">
        {currentPage} / {totalPages}
      </span>
      <Hoverable
        icon={FiChevronRight}
        onClick={currentPage === totalPages ? undefined : handleNext}
      />
    </div>
  );
}

export const HumanMessage = ({
  content,
  files,
  messageId,
  otherMessagesCanSwitchTo,
  onEdit,
  onMessageSelection,
}: {
  content: string;
  files?: FileDescriptor[];
  messageId?: number | null;
  otherMessagesCanSwitchTo?: number[];
  onEdit?: (editedContent: string) => void;
  onMessageSelection?: (messageId: number) => void;
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const [isHovered, setIsHovered] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState(content);

  useEffect(() => {
    if (!isEditing) {
      setEditedContent(content);
    }
  }, [content]);

  useEffect(() => {
    if (textareaRef.current) {
      // Focus the textarea
      textareaRef.current.focus();
      // Move the cursor to the end of the text
      textareaRef.current.selectionStart = textareaRef.current.value.length;
      textareaRef.current.selectionEnd = textareaRef.current.value.length;
    }
  }, [isEditing]);

  const handleEditSubmit = () => {
    if (editedContent.trim() !== content.trim()) {
      onEdit?.(editedContent);
    }
    setIsEditing(false);
  };

  const currentMessageInd = messageId
    ? otherMessagesCanSwitchTo?.indexOf(messageId)
    : undefined;

  return (
    <div
      className="pt-5 pb-1 px-5 flex -mr-6 w-full relative"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className="mx-auto w-searchbar-xs 2xl:w-searchbar-sm 3xl:w-searchbar">
        <div className="ml-8">
          <div className="flex">
            <div className="p-1 bg-user rounded-lg h-fit">
              <div className="text-inverted">
                <FiUser size={16} className="my-auto mx-auto" />
              </div>
            </div>

            <div className="font-bold text-emphasis ml-2 my-auto">You</div>
          </div>
          <div className="mx-auto mt-1 ml-8 w-searchbar-xs 2xl:w-searchbar-sm 3xl:w-searchbar-default flex flex-wrap">
            <div className="w-message-xs 2xl:w-message-sm 3xl:w-message-default break-words">
              {files && files.length > 0 && (
                <div className="mt-2 mb-4">
                  <div className="flex flex-wrap gap-2">
                    {files.map((file) => {
                      return <InMessageImage key={file.id} fileId={file.id} />;
                    })}
                  </div>
                </div>
              )}

              {isEditing ? (
                <div>
                  <div
                    className={`
                      opacity-100
                      w-full
                      flex
                      flex-col
                      border 
                      border-border 
                      rounded-lg 
                      bg-background-emphasis 
                      pb-2
                      [&:has(textarea:focus)]::ring-1
                      [&:has(textarea:focus)]::ring-black
                    `}
                  >
                    <textarea
                      ref={textareaRef}
                      className={`
                      m-0 
                      w-full 
                      h-auto
                      shrink
                      border-0
                      rounded-lg 
                      overflow-y-hidden
                      bg-background-emphasis 
                      whitespace-normal 
                      break-word
                      overscroll-contain
                      outline-none 
                      placeholder-gray-400 
                      resize-none
                      pl-4
                      pr-12 
                      py-4`}
                      aria-multiline
                      role="textarea"
                      value={editedContent}
                      style={{ scrollbarWidth: "thin" }}
                      onChange={(e) => {
                        setEditedContent(e.target.value);
                        e.target.style.height = "auto";
                        e.target.style.height = `${e.target.scrollHeight}px`;
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") {
                          e.preventDefault();
                          setEditedContent(content);
                          setIsEditing(false);
                        }
                      }}
                      // ref={(textarea) => {
                      //   if (textarea) {
                      //     textarea.selectionStart = textarea.selectionEnd =
                      //       textarea.value.length;
                      //   }
                      // }}
                    />
                    <div className="flex justify-end mt-2 gap-2 pr-4">
                      <button
                        className={`
                          w-fit 
                          p-1 
                          bg-accent 
                          text-inverted 
                          text-sm
                          rounded-lg 
                          hover:bg-accent-hover
                        `}
                        onClick={handleEditSubmit}
                      >
                        Submit
                      </button>
                      <button
                        className={`
                          w-fit 
                          p-1 
                          bg-hover
                          bg-background-strong 
                          text-sm
                          rounded-lg
                          hover:bg-hover-emphasis
                        `}
                        onClick={() => {
                          setEditedContent(content);
                          setIsEditing(false);
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                </div>
              ) : typeof content === "string" ? (
                <ReactMarkdown
                  className="prose max-w-full"
                  components={{
                    a: ({ node, ...props }) => (
                      <a
                        {...props}
                        className="text-blue-500 hover:text-blue-700"
                        target="_blank"
                        rel="noopener noreferrer"
                      />
                    ),
                  }}
                  remarkPlugins={[remarkGfm]}
                >
                  {content}
                </ReactMarkdown>
              ) : (
                content
              )}
            </div>
          </div>
          <div className="flex flex-col md:flex-row gap-x-0.5 ml-8 mt-1">
            {currentMessageInd !== undefined &&
              onMessageSelection &&
              otherMessagesCanSwitchTo &&
              otherMessagesCanSwitchTo.length > 1 && (
                <div className="mr-2">
                  <MessageSwitcher
                    currentPage={currentMessageInd + 1}
                    totalPages={otherMessagesCanSwitchTo.length}
                    handlePrevious={() =>
                      onMessageSelection(
                        otherMessagesCanSwitchTo[currentMessageInd - 1]
                      )
                    }
                    handleNext={() =>
                      onMessageSelection(
                        otherMessagesCanSwitchTo[currentMessageInd + 1]
                      )
                    }
                  />
                </div>
              )}
            {onEdit &&
            isHovered &&
            !isEditing &&
            (!files || files.length === 0) ? (
              <Hoverable
                icon={FiEdit2}
                onClick={() => {
                  setIsEditing(true);
                  setIsHovered(false);
                }}
              />
            ) : (
              <div className="h-[27px]" />
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
