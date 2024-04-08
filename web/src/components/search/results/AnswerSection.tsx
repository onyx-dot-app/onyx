import { Quote } from "@/lib/search/interfaces";
import { ResponseSection, StatusOptions } from "./ResponseSection";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const TEMP_STRING = "__$%^TEMP$%^__";

function replaceNewlines(answer: string) {
  // Since the one-shot answer is a JSON, GPT adds extra backslashes to the
  // newlines. This function replaces the extra backslashes with the correct
  // number of backslashes so that ReactMarkdown can render the newlines

  // Step 1: Replace '\\\\n' with a temporary placeholder
  answer = answer.replace(/\\\\n/g, TEMP_STRING);

  // Step 2: Replace '\\n' with '\n'
  answer = answer.replace(/\\n/g, "\n");

  // Step 3: Replace the temporary placeholder with '\\n'
  answer = answer.replace(TEMP_STRING, "\\n");

  return answer;
}

interface AnswerSectionProps {
  answer: string | null;
  quotes: Quote[] | null;
  error: string | null;
  nonAnswerableReason: string | null;
  isFetching: boolean;
}

export const AnswerSection = (props: AnswerSectionProps) => {
  let status = "in-progress" as StatusOptions;
  let header = <>Building answer...</>;
  let body = null;

  // finished answer
  if (props.quotes !== null || !props.isFetching) {
    status = "success";
    header = <>AI answer</>;
    if (props.answer) {
      body = (
        <ReactMarkdown
          className="prose text-sm max-w-full"
          remarkPlugins={[remarkGfm]}
        >
          {replaceNewlines(props.answer)}
        </ReactMarkdown>
      );
    } else {
      body = <div>Information not found</div>;
    }
    // error while building answer (NOTE: if error occurs during quote generation
    // the above if statement will hit and the error will not be displayed)
  } else if (props.error) {
    status = "failed";
    header = <>Error while building answer</>;
    body = (
      <div className="flex">
        <div className="text-error my-auto ml-1">{props.error}</div>
      </div>
    );
    // answer is streaming
  } else if (props.answer) {
    status = "success";
    header = <>AI answer</>;
    body = (
      <ReactMarkdown
        className="prose text-sm max-w-full"
        remarkPlugins={[remarkGfm]}
      >
        {replaceNewlines(props.answer)}
      </ReactMarkdown>
    );
  }
  if (props.nonAnswerableReason) {
    status = "warning";
    header = <>Building best effort AI answer...</>;
  }

  return (
    <ResponseSection
      status={status}
      header={
        <div className="flex">
          <div className="ml-2 text-strong">{header}</div>
        </div>
      }
      body={
        <div className="">
          {body}
          {props.nonAnswerableReason && !props.isFetching && (
            <div className="mt-4 text-sm">
              <b className="font-medium">Warning:</b> the AI did not think this
              question was answerable.{" "}
              <div className="italic mt-1 ml-2">
                {props.nonAnswerableReason}
              </div>
            </div>
          )}
        </div>
      }
      desiredOpenStatus={true}
      isNotControllable={true}
    />
  );
};
