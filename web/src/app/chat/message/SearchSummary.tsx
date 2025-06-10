import {
  BasicClickable,
  EmphasizedClickable,
} from "@/components/BasicClickable";
import { HoverPopup } from "@/components/HoverPopup";
import { Hoverable } from "@/components/Hoverable";
import { SourceIcon } from "@/components/SourceIcon";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { OnyxDocument } from "@/lib/search/interfaces";
import { useEffect, useRef, useState } from "react";
import { FiBook, FiCheck, FiEdit2, FiSearch, FiX } from "react-icons/fi";
import { FileResponse } from "../my-documents/DocumentsContext";

export function ShowHideDocsButton({
  messageId,
  isCurrentlyShowingRetrieved,
  handleShowRetrieved,
}: {
  messageId: number | null;
  isCurrentlyShowingRetrieved: boolean;
  handleShowRetrieved: (messageId: number | null) => void;
}) {
  return (
    <div
      className="ml-auto my-auto"
      onClick={() => handleShowRetrieved(messageId)}
    >
      {isCurrentlyShowingRetrieved ? (
        <EmphasizedClickable>
          <div className="w-24 text-xs">Hide Docs</div>
        </EmphasizedClickable>
      ) : (
        <BasicClickable>
          <div className="w-24 text-xs">Show Docs</div>
        </BasicClickable>
      )}
    </div>
  );
}

export function SearchSummary({
  index,
  query,
  finished,
  handleSearchQueryEdit,
  docs,
  toggleDocumentSelection,
  userFileSearch,
}: {
  index: number;
  finished: boolean;
  query: string;
  handleSearchQueryEdit?: (query: string) => void;
  docs: OnyxDocument[];
  toggleDocumentSelection: () => void;
  userFileSearch: boolean;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [finalQuery, setFinalQuery] = useState(query);
  const [isOverflowed, setIsOverflowed] = useState(false);
  const searchingForRef = useRef<HTMLDivElement>(null);
  const editQueryRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const checkOverflow = () => {
      const current = searchingForRef.current;
      if (current) {
        setIsOverflowed(
          current.scrollWidth > current.clientWidth ||
            current.scrollHeight > current.clientHeight
        );
      }
    };

    checkOverflow();
    window.addEventListener("resize", checkOverflow); // Recheck on window resize

    return () => window.removeEventListener("resize", checkOverflow);
  }, []);

  useEffect(() => {
    if (isEditing && editQueryRef.current) {
      editQueryRef.current.focus();
    }
  }, [isEditing]);

  useEffect(() => {
    if (!isEditing) {
      setFinalQuery(query);
    }
  }, [query, isEditing]);

  const searchingForDisplay = (
    <div className="flex flex-col gap-y-1">
      <div
        className={`flex items-center w-full rounded ${
          isOverflowed && "cursor-default"
        }`}
      >
        <FiSearch className="mobile:hidden flex-none mr-2" size={14} />
        <div
          className={`${
            !finished && "loading-text"
          } text-xs desktop:text-sm mobile:ml-auto !line-clamp-1 !break-all px-0.5 flex-grow`}
          ref={searchingForRef}
        >
          {userFileSearch ? (
            "Reading context"
          ) : (
            <>
              {finished ? "Searched" : "Searching"} for:{" "}
              <i>
                {index === 1
                  ? finalQuery.length > 50
                    ? `${finalQuery.slice(0, 50)}...`
                    : finalQuery
                  : finalQuery}
              </i>
            </>
          )}
        </div>
      </div>

      <div className="desktop:hidden">
        {" "}
        {docs && (
          <button
            className="cursor-pointer mr-2 flex items-center gap-0.5"
            onClick={() => toggleDocumentSelection()}
          >
            {Array.from(new Set(docs.map((doc) => doc.source_type)))
              .slice(0, 3)
              .map((sourceType, idx) => (
                <div key={idx} className="rounded-full">
                  <SourceIcon sourceType={sourceType} iconSize={14} />
                </div>
              ))}
            {Array.from(new Set(docs.map((doc) => doc.source_type))).length >
              3 && (
              <div className="rounded-full bg-background-200 w-3.5 h-3.5 flex items-center justify-center">
                <span className="text-[8px]">
                  +
                  {Array.from(new Set(docs.map((doc) => doc.source_type)))
                    .length - 3}
                </span>
              </div>
            )}
            <span className="text-xs underline">View sources</span>
          </button>
        )}
      </div>
    </div>
  );

  const editInput = handleSearchQueryEdit ? (
    <div className="mobile:hidden flex w-full mr-3">
      <div className="w-full">
        <input
          ref={editQueryRef}
          value={finalQuery}
          onChange={(e) => setFinalQuery(e.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              setIsEditing(false);
              if (!finalQuery) {
                setFinalQuery(query);
              } else if (finalQuery !== query) {
                handleSearchQueryEdit(finalQuery);
              }
              event.preventDefault();
            } else if (event.key === "Escape") {
              setFinalQuery(query);
              setIsEditing(false);
              event.preventDefault();
            }
          }}
          className="px-1 py-0.5 h-[22px] text-sm mr-2 w-full rounded-sm border border-border-strong"
        />
      </div>
      <div className="ml-2 -my-1 my-auto flex">
        <Hoverable
          icon={FiCheck}
          onClick={() => {
            if (!finalQuery) {
              setFinalQuery(query);
            } else if (finalQuery !== query) {
              handleSearchQueryEdit(finalQuery);
            }
            setIsEditing(false);
          }}
        />
        <Hoverable
          icon={FiX}
          onClick={() => {
            setFinalQuery(query);
            setIsEditing(false);
          }}
        />
      </div>
    </div>
  ) : null;

  return (
    <div className="flex group w-fit items-center">
      {isEditing ? (
        editInput
      ) : (
        <>
          <div className="mobile:w-full mobile:mr-2 text-sm mobile:flex-grow">
            {isOverflowed ? (
              <HoverPopup
                mainContent={searchingForDisplay}
                popupContent={
                  <div>
                    <b>Full query:</b>{" "}
                    <div className="mt-1 italic">{query}</div>
                  </div>
                }
                direction="top"
              />
            ) : (
              searchingForDisplay
            )}
          </div>

          {handleSearchQueryEdit && (
            <TooltipProvider delayDuration={1000}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    className="ml-2 -my-2 mobile:hidden hover:bg-accent-background-hovered p-1 rounded flex-shrink-0 group-hover:opacity-100 opacity-0"
                    onClick={() => {
                      setIsEditing(true);
                    }}
                  >
                    <FiEdit2 />
                  </button>
                </TooltipTrigger>
                <TooltipContent>Edit Search</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
        </>
      )}
    </div>
  );
}

export function UserKnowledgeFiles({
  userKnowledgeFiles,
}: {
  userKnowledgeFiles: FileResponse[];
}): JSX.Element {
  if (!userKnowledgeFiles || userKnowledgeFiles.length === 0) {
    return <></>;
  }

  return (
    <div className="flex group w-fit items-center mb-1">
      <div className="flex items-center text-xs desktop:text-sm">
        <FiBook className="mobile:hidden flex-none mr-2" size={14} />
        <span className="text-xs desktop:text-sm">
          Referenced {userKnowledgeFiles.length}{" "}
          {userKnowledgeFiles.length === 1 ? "document" : "documents"}
        </span>
      </div>
    </div>
  );
}
