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
import { ProjectFile } from "../projects/projectsService";
import { BlinkingDot } from "./BlinkingDot";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";

export const MemoizedAnchor = memo(
  ({
    docs,
    subQuestions,
    openQuestion,
    userFiles,
    href,
    updatePresentingDocument,
    children,
  }: {
    subQuestions?: SubQuestionDetail[];
    openQuestion?: (question: SubQuestionDetail) => void;
    docs?: OnyxDocument[] | null;
    userFiles?: ProjectFile[] | null;
    updatePresentingDocument: (doc: OnyxDocument) => void;
    href?: string;
    children: React.ReactNode;
  }): JSX.Element => {
    const value = children?.toString();
    if (value?.startsWith("[") && value?.endsWith("]")) {
      const match = value.match(/\[(D|Q)?(\d+)\]/);
      if (match) {
        const match_item = match[2];
        if (match_item !== undefined) {
          const isUserFileCitation = userFiles?.length && userFiles.length > 0;
          if (isUserFileCitation) {
            const index = Math.min(
              parseInt(match_item, 10) - 1,
              userFiles?.length - 1
            );
            const associatedUserFile = userFiles?.[index];
            if (!associatedUserFile) {
              return <a href={children as string}>{children}</a>;
            }
          } else if (!isUserFileCitation) {
            const index = parseInt(match_item, 10) - 1;
            const associatedDoc = docs?.[index];
            if (!associatedDoc) {
              return <a href={children as string}>{children}</a>;
            }
          } else {
            const index = parseInt(match_item, 10) - 1;
            const associatedSubQuestion = subQuestions?.[index];
            if (!associatedSubQuestion) {
              return <a href={href || (children as string)}>{children}</a>;
            }
          }
        }
      }

      if (match) {
        const match_item = match[2];
        if (match_item !== undefined) {
          const isSubQuestion = match[1] === "Q";
          const isDocument = !isSubQuestion;

          // Fix: parseInt now uses match[2], which is the numeric part
          const index = parseInt(match_item, 10) - 1;

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
      return <BlinkingDot addMargin />;
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

      if (url && !url.includes("://")) {
        // Only add https:// if the URL doesn't already have a protocol
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
  function MemoizedParagraph({ className, children }: any) {
    return (
      <Text mainContentBody className={className}>
        {children}
      </Text>
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
