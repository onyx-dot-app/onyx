import {
  Citation,
  QuestionCardProps,
  DocumentCardProps,
} from "@/components/search/results/Citation";
import { LoadedOnyxDocument, OnyxDocument } from "@/lib/search/interfaces";
import React, { memo } from "react";
import isEqual from "lodash/isEqual";
import { SourceIcon } from "@/components/SourceIcon";
import { WebResultIcon } from "@/components/WebResultIcon";
import { SubQuestionDetail } from "../interfaces";
import { ValidSources } from "@/lib/types";

export const MemoizedAnchor = memo(
  ({
    docs,
    subQuestions,
    openQuestion,
    href,
    updatePresentingDocument,
    children,
  }: {
    subQuestions?: SubQuestionDetail[];
    openQuestion?: (question: SubQuestionDetail) => void;
    docs?: OnyxDocument[] | null;
    updatePresentingDocument: (doc: OnyxDocument) => void;
    href?: string;
    children: React.ReactNode;
  }): JSX.Element => {
    const value = children?.toString();
    if (value?.startsWith("[") && value?.endsWith("]")) {
      const match = value.match(/\[(D|Q)?(\d+)\]/);
      if (match) {
        const isSubQuestion = match[1] === "Q";
        if (!isSubQuestion) {
          const index = parseInt(match[2], 10) - 1;
          const associatedDoc = docs?.[index];
          if (!associatedDoc) {
            return <a href={children as string}>{children}</a>;
          }
        } else {
          const index = parseInt(match[2], 10) - 1;
          const associatedSubQuestion = subQuestions?.[index];
          if (!associatedSubQuestion) {
            return <a href={href || (children as string)}>{children}</a>;
          }
        }
      }

      if (match) {
        const isSubQuestion = match[1] === "Q";
        const isDocument = !isSubQuestion;

        // Fix: parseInt now uses match[2], which is the numeric part
        const index = parseInt(match[2], 10) - 1;

        const associatedDoc = isDocument ? docs?.[index] : null;
        const associatedSubQuestion = isSubQuestion
          ? subQuestions?.[index]
          : undefined;

        if (!associatedDoc && !associatedSubQuestion) {
          return <>{children}</>;
        }

        let icon: React.ReactNode = null;
        if (associatedDoc?.source_type === "web") {
          icon = <WebResultIcon url={associatedDoc.link} />;
        } else {
          icon = (
            <SourceIcon
              sourceType={associatedDoc?.source_type as ValidSources}
              iconSize={18}
            />
          );
        }
        const associatedDocInfo = associatedDoc
          ? {
              ...associatedDoc,
              icon: icon as any,
              link: associatedDoc.link,
            }
          : undefined;

        return (
          <MemoizedLink
            updatePresentingDocument={updatePresentingDocument}
            href={href}
            document={associatedDocInfo}
            question={associatedSubQuestion}
            openQuestion={openQuestion}
          >
            {children}
          </MemoizedLink>
        );
      }
    }
    return (
      <MemoizedLink
        updatePresentingDocument={updatePresentingDocument}
        href={href}
      >
        {children}
      </MemoizedLink>
    );
  }
);

export const MemoizedLink = memo(
  ({
    node,
    document,
    updatePresentingDocument,
    question,
    href,
    openQuestion,
    ...rest
  }: Partial<DocumentCardProps & QuestionCardProps> & {
    node?: any;
    [key: string]: any;
  }) => {
    const value = rest.children;
    const questionCardProps: QuestionCardProps | undefined =
      question && openQuestion
        ? {
            question: question,
            openQuestion: openQuestion,
          }
        : undefined;

    const documentCardProps: DocumentCardProps | undefined =
      document && updatePresentingDocument
        ? {
            url: document.link,
            icon: document.icon as unknown as React.ReactNode,
            document: document as LoadedOnyxDocument,
            updatePresentingDocument: updatePresentingDocument!,
          }
        : undefined;

    if (value?.toString().startsWith("*")) {
      return (
        <div className="flex-none bg-background-800 inline-block rounded-full h-3 w-3 ml-2" />
      );
    } else if (value?.toString().startsWith("[")) {
      return (
        <>
          {documentCardProps ? (
            <Citation document_info={documentCardProps}>
              {rest.children}
            </Citation>
          ) : (
            <Citation question_info={questionCardProps}>
              {rest.children}
            </Citation>
          )}
        </>
      );
    }

    const handleMouseDown = () => {
      let url = href || rest.children?.toString();
      if (url && !url.startsWith("http://") && !url.startsWith("https://")) {
        // Try to construct a valid URL
        const httpsUrl = `https://${url}`;
        try {
          new URL(httpsUrl);
          url = httpsUrl;
        } catch {
          // If not a valid URL, don't modify original url
        }
      }
      window.open(url, "_blank");
    };
    return (
      <a
        onMouseDown={handleMouseDown}
        className="cursor-pointer text-link hover:text-link-hover"
      >
        {rest.children}
      </a>
    );
  }
);

export const MemoizedParagraph = memo(
  function MemoizedParagraph({ children, fontSize }: any) {
    return (
      <p
        className={`text-neutral-900 dark:text-neutral-200 my-0 ${
          fontSize === "sm" ? "leading-tight text-sm" : ""
        }`}
      >
        {children}
      </p>
    );
  },
  (prevProps, nextProps) => {
    const areEqual = isEqual(prevProps.children, nextProps.children);
    return areEqual;
  }
);

MemoizedAnchor.displayName = "MemoizedAnchor";
MemoizedLink.displayName = "MemoizedLink";
MemoizedParagraph.displayName = "MemoizedParagraph";
