import { ReactNode } from "react";
import { CompactDocumentCard, CompactQuestionCard } from "../DocumentDisplay";
import { LoadedOnyxDocument, OnyxDocument } from "@/lib/search/interfaces";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { openDocument } from "@/lib/search/utils";
import { SubQuestionDetail } from "@/app/chat/interfaces";
import { getFileIconFromFileNameAndLink } from "@/lib/assistantIconUtils";
import { getSourceDisplayName } from "@/lib/sources";
import { ValidSources } from "@/lib/types";

const MAX_CITATION_TEXT_LENGTH = 40;

export interface DocumentCardProps {
  document: LoadedOnyxDocument;
  updatePresentingDocument: (document: OnyxDocument) => void;
  icon?: React.ReactNode;
  url?: string;
}
export interface QuestionCardProps {
  question: SubQuestionDetail;
  openQuestion: (question: SubQuestionDetail) => void;
}

function truncateText(str: string, maxLength: number) {
  if (str.length <= maxLength) return str;
  return str.slice(0, maxLength) + "...";
}

export function Citation({
  children,
  document_info,
  question_info,
  index,
}: {
  document_info?: DocumentCardProps;
  question_info?: QuestionCardProps;
  children?: JSX.Element | string | null | ReactNode;
  index?: number;
}) {
  let innerText = "";
  if (index !== undefined) {
    innerText = index.toString();
  }

  if (children) {
    const childrenString = children.toString();
    const childrenSegment1 = childrenString.split("[")[1];
    if (childrenSegment1 !== undefined) {
      const childrenSegment1_0 = childrenSegment1.split("]")[0];
      if (childrenSegment1_0 !== undefined) {
        innerText = childrenSegment1_0;
      }
    }
  }

  if (!document_info && !question_info) {
    return <>{children}</>;
  }
  const icon = document_info?.document
    ? getFileIconFromFileNameAndLink(
        document_info.document.semantic_identifier || "",
        document_info.document.link || ""
      )
    : null;

  const sourceType = document_info?.document?.source_type;
  const title = document_info?.document?.semantic_identifier;
  const citationText =
    (sourceType && sourceType != ValidSources.Web
      ? getSourceDisplayName(sourceType)
      : truncateText(title || "", MAX_CITATION_TEXT_LENGTH)) || "Unknown";

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            onClick={() => {
              document_info?.document
                ? openDocument(
                    document_info.document,
                    document_info.updatePresentingDocument
                  )
                : question_info?.question
                  ? question_info.openQuestion(question_info.question)
                  : null;
            }}
            className="inline-flex items-center cursor-pointer transition-all duration-200 ease-in-out"
          >
            <span
              className="flex items-center justify-center px-1 h-4 text-[10px] 
                         font-medium text-text-700 bg-background-150 rounded-md 
                         hover:bg-background-900 hover:text-text-100 shadow-sm mr-0.5 ml-0.5"
              style={{ transform: "translateY(-10%)", lineHeight: "1" }}
            >
              {citationText}
            </span>
          </span>
        </TooltipTrigger>
        <TooltipContent
          className="border border-neutral-300 hover:text-neutral-900 
                     bg-neutral-100 dark:!bg-[#000] dark:border-neutral-700"
          width="mb-2 max-w-lg"
        >
          {document_info?.document ? (
            <CompactDocumentCard
              updatePresentingDocument={document_info.updatePresentingDocument}
              url={document_info.url}
              icon={icon}
              document={document_info.document}
            />
          ) : (
            <CompactQuestionCard
              question={question_info?.question!}
              openQuestion={question_info?.openQuestion!}
            />
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
