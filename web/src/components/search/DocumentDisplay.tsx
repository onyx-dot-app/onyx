"use client";
import React from "react";
import {
  OnyxDocument,
  DocumentRelevance,
  SearchOnyxDocument,
} from "@/lib/search/interfaces";
import { DocumentFeedbackBlock } from "./DocumentFeedbackBlock";
import { useContext, useState } from "react";
import { PopupSpec } from "../admin/connectors/Popup";
import { DocumentUpdatedAtBadge } from "./DocumentUpdatedAtBadge";
import { SourceIcon } from "../SourceIcon";
import { MetadataBadge } from "../MetadataBadge";
import { BookIcon, LightBulbIcon } from "../icons/icons";

import { FaStar } from "react-icons/fa";
import { FiTag } from "react-icons/fi";
import { SettingsContext } from "../settings/SettingsProvider";
import { CustomTooltip, TooltipGroup } from "../tooltip/CustomTooltip";
import { WarningCircle } from "@phosphor-icons/react";
import TextView from "../chat/TextView";
import { openDocument } from "@/lib/search/utils";
import { SubQuestionDetail } from "@/app/chat/interfaces";

export const buildDocumentSummaryDisplay = (
  matchHighlights: string[],
  blurb: string
) => {
  // if there are no match highlights, or if it's really short, just use the blurb
  // this is to prevent the UI from showing something like `...` for the summary
  const MIN_MATCH_HIGHLIGHT_LENGTH = 5;
  if (
    !matchHighlights ||
    matchHighlights.length <= MIN_MATCH_HIGHLIGHT_LENGTH
  ) {
    return blurb;
  }

  // content, isBold, isContinuation
  let sections = [] as [string, boolean, boolean][];
  matchHighlights.forEach((matchHighlight, matchHighlightIndex) => {
    if (!matchHighlight) {
      return;
    }

    const words = matchHighlight.split(new RegExp("\\s"));
    words.forEach((word) => {
      if (!word) {
        return;
      }

      let isContinuation = false;
      while (word.includes("<hi>") && word.includes("</hi>")) {
        const start = word.indexOf("<hi>");
        const end = word.indexOf("</hi>");
        const before = word.slice(0, start);
        const highlight = word.slice(start + 4, end);
        const after = word.slice(end + 5);

        if (before) {
          sections.push([before, false, isContinuation]);
          isContinuation = true;
        }
        sections.push([highlight, true, isContinuation]);
        isContinuation = true;
        word = after;
      }

      if (word) {
        sections.push([word, false, isContinuation]);
      }
    });
    if (matchHighlightIndex != matchHighlights.length - 1) {
      sections.push(["...", false, false]);
    }
  });

  if (sections.length == 0) {
    return;
  }

  const firstSection = sections[0];
  if (firstSection === undefined) {
    return;
  }

  let previousIsContinuation = firstSection[2];
  let previousIsBold = firstSection[1];
  let currentText = "";
  const finalJSX = [] as (JSX.Element | string)[];
  sections.forEach(([word, shouldBeBold, isContinuation], index) => {
    if (shouldBeBold != previousIsBold) {
      if (currentText) {
        if (previousIsBold) {
          // remove leading space so that we don't bold the whitespace
          // in front of the matching keywords
          currentText = currentText.trim();
          if (!previousIsContinuation) {
            finalJSX[finalJSX.length - 1] = finalJSX[finalJSX.length - 1] + " ";
          }
          finalJSX.push(
            <b key={index} className="text-text font-bold">
              {currentText}
            </b>
          );
        } else {
          finalJSX.push(currentText);
        }
      }
      currentText = "";
    }
    previousIsBold = shouldBeBold;
    previousIsContinuation = isContinuation;
    if (!isContinuation || index === 0) {
      currentText += " ";
    }
    currentText += word;
  });
  if (currentText) {
    if (previousIsBold) {
      currentText = currentText.trim();
      if (!previousIsContinuation) {
        finalJSX[finalJSX.length - 1] = finalJSX[finalJSX.length - 1] + " ";
      }
      finalJSX.push(
        <b key={sections.length} className="text-default bg-highlight-text">
          {currentText}
        </b>
      );
    } else {
      finalJSX.push(currentText);
    }
  }
  return finalJSX;
};

export function DocumentMetadataBlock({
  document,
}: {
  document: OnyxDocument;
}) {
  // don't display super long tags, as they are ugly
  const MAXIMUM_TAG_LENGTH = 40;

  return (
    <div className="flex flex-wrap gap-1">
      {document.updated_at && (
        <div className="pr-1">
          <DocumentUpdatedAtBadge updatedAt={document.updated_at} />
        </div>
      )}

      {Object.entries(document.metadata).length > 0 && (
        <>
          <div className="pl-1 border-l border-border" />
          {Object.entries(document.metadata)
            .filter(
              ([key, value]) => (key + value).length <= MAXIMUM_TAG_LENGTH
            )
            .map(([key, value]) => {
              return (
                <MetadataBadge
                  key={key}
                  icon={FiTag}
                  value={`${key}=${value}`}
                />
              );
            })}
        </>
      )}
    </div>
  );
}

interface DocumentDisplayProps {
  document: SearchOnyxDocument;
  messageId: number | null;
  documentRank: number;
  isSelected: boolean;
  setPopup: (popupSpec: PopupSpec | null) => void;
  hide?: boolean;
  index?: number;
  contentEnriched?: boolean;
  additional_relevance: DocumentRelevance | null;
}

export const DocumentDisplay = ({
  document,
  isSelected,
  additional_relevance,
  messageId,
  contentEnriched,
  documentRank,
  hide,
  index,
  setPopup,
}: DocumentDisplayProps) => {
  const [isHovered, setIsHovered] = useState(false);
  const [alternativeToggled, setAlternativeToggled] = useState(false);
  const relevance_explanation =
    document.relevance_explanation ?? additional_relevance?.content;
  const settings = useContext(SettingsContext);
  const [presentingDocument, setPresentingDocument] =
    useState<OnyxDocument | null>(null);

  const handleViewFile = async () => {
    setPresentingDocument(document);
  };

  return (
    <div
      key={document.semantic_identifier}
      className={`text-sm mobile:ml-4 border-b border-border transition-all duration-500 
        ${hide ? "transform translate-x-full opacity-0" : ""} 
        ${!hide ? "pt-3" : "border-transparent"} relative`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      style={{
        transitionDelay: `${index! * 10}ms`, // Add a delay to the transition based on index
      }}
    >
      <div
        className={`absolute top-6 overflow-y-auto -translate-y-2/4 flex ${
          isSelected ? "-left-14 w-14" : "-left-10 w-10"
        }`}
      >
        {!hide && (document.is_relevant || additional_relevance?.relevant) && (
          <FaStar
            size={16}
            className="h-full text-xs text-star-indicator rounded w-fit my-auto select-none ml-auto mr-2"
          />
        )}
      </div>
      <div
        className={`collapsible ${
          hide ? "collapsible-closed overflow-y-auto border-transparent" : ""
        }`}
      >
        <div className="flex relative">
          <button
            type="button"
            className={`rounded-lg flex font-bold text-link max-w-full`}
            onClick={() => {
              if (document.link) {
                window.open(document.link, "_blank");
              } else {
                handleViewFile();
              }
            }}
          >
            <SourceIcon sourceType={document.source_type} iconSize={22} />
            <p className="truncate text-wrap break-all ml-2 my-auto line-clamp-1 text-base max-w-full">
              {document.semantic_identifier || document.document_id}
            </p>
          </button>
          <div className="ml-auto flex items-center">
            <TooltipGroup>
              {isHovered && messageId && (
                <DocumentFeedbackBlock
                  documentId={document.document_id}
                  messageId={messageId}
                  documentRank={documentRank}
                  setPopup={setPopup}
                />
              )}
              {(contentEnriched || additional_relevance) &&
                relevance_explanation &&
                (isHovered || alternativeToggled || settings?.isMobile) && (
                  <button
                    onClick={() =>
                      setAlternativeToggled(
                        (alternativeToggled) => !alternativeToggled
                      )
                    }
                  >
                    <CustomTooltip showTick line content="Toggle content">
                      <LightBulbIcon
                        className={`${
                          settings?.isMobile && alternativeToggled
                            ? "text-green-600"
                            : "text-blue-600"
                        } my-auto ml-2 h-4 w-4 cursor-pointer`}
                      />
                    </CustomTooltip>
                  </button>
                )}
            </TooltipGroup>
          </div>
        </div>
        <div className="mt-1">
          <DocumentMetadataBlock document={document} />
        </div>

        {presentingDocument && (
          <TextView
            presentingDocument={presentingDocument}
            onClose={() => setPresentingDocument(null)}
          />
        )}

        <p
          style={{ transition: "height 0.30s ease-in-out" }}
          className="pl-1 pt-2 pb-3 break-words text-wrap"
        >
          {alternativeToggled && (contentEnriched || additional_relevance)
            ? relevance_explanation
            : buildDocumentSummaryDisplay(
                document.match_highlights,
                document.blurb
              )}
        </p>
      </div>
    </div>
  );
};

export const AgenticDocumentDisplay = ({
  document,
  contentEnriched,
  additional_relevance,
  messageId,
  documentRank,
  index,
  hide,
  setPopup,
}: DocumentDisplayProps) => {
  const [isHovered, setIsHovered] = useState(false);
  const [presentingDocument, setPresentingDocument] =
    useState<OnyxDocument | null>(null);

  const [alternativeToggled, setAlternativeToggled] = useState(false);

  const relevance_explanation =
    document.relevance_explanation ?? additional_relevance?.content;

  return (
    <div
      key={document.semantic_identifier}
      className={`text-sm mobile:ml-4 border-b border-border transition-all duration-500
      ${!hide ? "transform translate-x-full opacity-0" : ""} 
      ${hide ? "py-3" : "border-transparent"} relative`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      style={{
        transitionDelay: `${index! * 10}ms`,
      }}
    >
      <div
        className={`collapsible ${
          !hide && "collapsible-closed overflow-y-auto border-transparent"
        }`}
      >
        <div className="flex relative">
          <button
            type="button"
            className={`rounded-lg flex font-bold text-link max-w-full ${
              document.link ? "" : "pointer-events-none"
            }`}
            onClick={() => {
              if (document.link) {
                window.open(document.link, "_blank");
              } else {
                setPresentingDocument(document);
              }
            }}
          >
            <SourceIcon sourceType={document.source_type} iconSize={22} />
            <p className="truncate text-wrap break-all ml-2 my-auto line-clamp-1 text-base max-w-full">
              {document.semantic_identifier || document.document_id}
            </p>
          </button>

          <div className="ml-auto items-center flex">
            <TooltipGroup>
              {isHovered && messageId && (
                <DocumentFeedbackBlock
                  documentId={document.document_id}
                  messageId={messageId}
                  documentRank={documentRank}
                  setPopup={setPopup}
                />
              )}

              {(contentEnriched || additional_relevance) &&
                (isHovered || alternativeToggled) && (
                  <button
                    onClick={() =>
                      setAlternativeToggled(
                        (alternativeToggled) => !alternativeToggled
                      )
                    }
                  >
                    <CustomTooltip showTick line content="Toggle content">
                      <BookIcon className="ml-2 my-auto text-blue-400" />
                    </CustomTooltip>
                  </button>
                )}
            </TooltipGroup>
          </div>
        </div>
        <div className="mt-1">
          <DocumentMetadataBlock document={document} />
        </div>
        {presentingDocument && (
          <TextView
            presentingDocument={presentingDocument}
            onClose={() => setPresentingDocument(null)}
          />
        )}

        <div className="pt-2 break-words flex gap-x-2">
          <p
            className="break-words text-wrap"
            style={{ transition: "height 0.30s ease-in-out" }}
          >
            {alternativeToggled && (contentEnriched || additional_relevance)
              ? buildDocumentSummaryDisplay(
                  document.match_highlights,
                  document.blurb
                )
              : relevance_explanation || (
                  <span className="flex gap-x-1 items-center">
                    {" "}
                    <WarningCircle />
                    Model failed to produce an analysis of the document
                  </span>
                )}
          </p>
        </div>
      </div>
    </div>
  );
};

export function CompactDocumentCard({
  document,
  icon,
  url,
  updatePresentingDocument,
}: {
  document: OnyxDocument;
  icon?: React.ReactNode;
  url?: string;
  updatePresentingDocument: (document: OnyxDocument) => void;
}) {
  return (
    <div
      onClick={() => {
        openDocument(document, updatePresentingDocument);
      }}
      className="max-w-[250px]  gap-y-1 cursor-pointer pb-0 pt-0 mt-0 flex gap-y-0  flex-col  content-start items-start gap-0 "
    >
      <div className="text-sm  flex gap-x-2 !pb-0 !mb-0 font-semibold flex  items-center gap-x-1 text-text-900 pt-0 mt-0  w-full">
        {icon}
        <p className="gap-0 p-0 m-0 line-clamp-2">
          {(document.semantic_identifier || document.document_id).slice(0, 40)}
          {(document.semantic_identifier || document.document_id).length > 40 &&
            "..."}
        </p>
      </div>
      {document.blurb && (
        <div className="text-xs mb-0 text-neutral-600 dark:text-neutral-300 line-clamp-2">
          {document.blurb}
        </div>
      )}
      {document.updated_at && (
        <div className=" flex mt-0 pt-0 items-center justify-between w-full ">
          {!isNaN(new Date(document.updated_at).getTime()) && (
            <span className="text-xs text-text-500">
              Updated {new Date(document.updated_at).toLocaleDateString()}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export function CompactQuestionCard({
  question,
  openQuestion,
}: {
  question: SubQuestionDetail;
  openQuestion: (question: SubQuestionDetail) => void;
}) {
  return (
    <div
      onClick={() => openQuestion(question)}
      className="max-w-[350px] gap-y-1 cursor-pointer pb-0 pt-0 mt-0 flex gap-y-0 flex-col content-start items-start gap-0"
    >
      <div className="text-sm !pb-0 !mb-0 font-semibold flex items-center gap-x-1 text-text-900 pt-0 mt-0 truncate w-full">
        Question
      </div>
      <div className="text-xs mb-0 text-text-600 line-clamp-2">
        {question.question}
      </div>
      <div className="flex mt-0 pt-0 items-center justify-between w-full">
        <span className="text-xs text-text-500">
          {question.context_docs?.top_documents.length || 0} context docs
        </span>
        {question.sub_queries && (
          <span className="text-xs text-text-500">
            {question.sub_queries.length} subqueries
          </span>
        )}
      </div>
    </div>
  );
}
