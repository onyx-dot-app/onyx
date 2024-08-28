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
  isFetching: boolean;
}

export const AnswerSection = (props: AnswerSectionProps) => {
  let status = "in-progress" as StatusOptions;
  let header = <></>;
  let body = null;

  // finished answer
  if (props.quotes !== null || !props.isFetching) {
    status = "success";
    header = <></>;

    body = (
      <ReactMarkdown
        className="prose text-sm max-w-full"
        remarkPlugins={[remarkGfm]}
      >
        {replaceNewlines(props.answer || "")}
      </ReactMarkdown>
    );

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
    header = <></>;
    body = (
      <ReactMarkdown
        className="prose text-sm max-w-full"
        remarkPlugins={[remarkGfm]}
      >
        {replaceNewlines(props.answer)}
      </ReactMarkdown>
    );
  }

  return (
    <ResponseSection
      status={status}
      header={
        <div className="flex">
          <div className="ml-2 text-strong">{header}</div>
        </div>
      }
      body={<div className="">{body}</div>}
      desiredOpenStatus={true}
      isNotControllable={true}
    />
  );
};
