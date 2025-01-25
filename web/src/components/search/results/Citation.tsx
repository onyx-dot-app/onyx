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
  const innerText = children
    ? children?.toString().split("[")[1].split("]")[0]
    : index;

  if (!document_info && !question_info) {
    return (
      <div
        className="debug-info"
        style={{
          backgroundColor: "#f0f0f0",
          padding: "10px",
          border: "1px solid #ccc",
          margin: "5px 0",
        }}
      >
        <h4>Debug Info:</h4>
        <p>document_info: {JSON.stringify(document_info)}</p>
        <p>question_info: {JSON.stringify(question_info)}</p>
        <p>No document or question info available.</p>
      </div>
    );
  }
  return (
    <TooltipProvider delayDuration={0}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
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
            <span className="flex items-center justify-center w-5 h-5 text-[11px] font-medium text-gray-700 bg-neutral-100 rounded-full border border-gray-300 hover:bg-gray-200 hover:text-gray-900 shadow-sm">
              {innerText}
            </span>
          </div>
        </TooltipTrigger>
        <TooltipContent
          width="mb-2 max-w-lg"
          className="border-2 border-border shadow-lg bg-white"
        >
          {document_info?.document ? (
            <CompactDocumentCard
              updatePresentingDocument={document_info.updatePresentingDocument}
              url={document_info.url}
              icon={document_info.icon}
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
