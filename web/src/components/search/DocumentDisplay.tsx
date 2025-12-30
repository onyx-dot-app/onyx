"use client";
import React, { JSX } from "react";
import { OnyxDocument } from "@/lib/search/interfaces";
import { SourceIcon } from "../SourceIcon";
import { WebResultIcon } from "../WebResultIcon";
import Text from "@/refresh-components/texts/Text";
import { openDocument } from "@/lib/search/utils";
import { SubQuestionDetail } from "@/app/chat/interfaces";
import { ValidSources } from "@/lib/types";
import { Card } from "@/components/ui/card";

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

interface CompactDocumentCardProps {
  document: OnyxDocument;
  updatePresentingDocument: (document: OnyxDocument) => void;
}

export function CompactDocumentCard({
  document,
  updatePresentingDocument,
}: CompactDocumentCardProps) {
  const isWebSource =
    document.is_internet || document.source_type === ValidSources.Web;

  return (
    <Card className="shadow-00 w-[20rem]">
      <button
        onClick={() => {
          openDocument(document, updatePresentingDocument);
        }}
        className="max-w-[20rem] p-3 flex flex-col gap-1"
      >
        <div className="flex flex-row gap-2 items-center w-full">
          {isWebSource && document.link ? (
            <WebResultIcon url={document.link} size={18} />
          ) : (
            <SourceIcon sourceType={document.source_type} iconSize={18} />
          )}
          <Text as="p" text04 className="truncate !m-0">
            {document.semantic_identifier ?? document.document_id}
          </Text>
        </div>

        {document.blurb && (
          <Text
            as="p"
            text03
            secondaryBody
            className="line-clamp-2 text-left !m-0"
          >
            {document.blurb}
          </Text>
        )}

        {document.updated_at &&
          !isNaN(new Date(document.updated_at).getTime()) && (
            <Text
              as="p"
              text03
              figureSmallLabel
              className="line-clamp-2 text-left !m-0"
            >
              Updated {new Date(document.updated_at).toLocaleDateString()}
            </Text>
          )}
      </button>
    </Card>
  );
}

interface CompactQuestionCardProps {
  question: SubQuestionDetail;
  openQuestion: (question: SubQuestionDetail) => void;
}

export function CompactQuestionCard({
  question,
  openQuestion,
}: CompactQuestionCardProps) {
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
