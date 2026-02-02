import {
  QuestionCardProps,
  DocumentCardProps,
} from "@/components/search/results/Citation";
import { LoadedOnyxDocument, OnyxDocument } from "@/lib/search/interfaces";
import React, { memo, JSX, useMemo, useCallback } from "react";
import { SourceIcon } from "@/components/SourceIcon";
import { WebResultIcon } from "@/components/WebResultIcon";
import { SubQuestionDetail, CitationMap } from "../interfaces";
import { ValidSources } from "@/lib/types";
import { ProjectFile } from "../projects/projectsService";
import { BlinkingDot } from "./BlinkingDot";
import Text from "@/refresh-components/texts/Text";
import SourceTag from "@/refresh-components/buttons/source-tag/SourceTag";
import {
  documentToSourceInfo,
  questionToSourceInfo,
  getDisplayNameForSource,
} from "@/refresh-components/buttons/source-tag/sourceTagUtils";
import { openDocument } from "@/lib/search/utils";

export const MemoizedAnchor = memo(
  ({
    docs,
    subQuestions,
    openQuestion,
    userFiles,
    citations,
    href,
    updatePresentingDocument,
    children,
  }: {
    subQuestions?: SubQuestionDetail[];
    openQuestion?: (question: SubQuestionDetail) => void;
    docs?: OnyxDocument[] | null;
    userFiles?: ProjectFile[] | null;
    citations?: CitationMap;
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
          const isSubQuestion = match[1] === "Q";
          const isDocument = !isSubQuestion;

          const citation_num = parseInt(match_item, 10);

          // Use citation map to find the correct document
          // Citations map format: {citation_num: document_id}
          // e.g., {1: "doc_abc", 2: "doc_xyz", 3: "doc_123"}
          let associatedDoc: OnyxDocument | null = null;
          if (isDocument && docs && citations) {
            const document_id = citations[citation_num];
            if (document_id) {
              associatedDoc =
                docs.find((d) => d.document_id === document_id) || null;
            }
          }

          const associatedSubQuestion = isSubQuestion
            ? subQuestions?.[citation_num - 1]
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

    // Convert document to SourceInfo for SourceTag
    const documentSourceInfo = useMemo(() => {
      if (!document) return null;
      return documentToSourceInfo(document as OnyxDocument);
    }, [document]);

    // Convert question to SourceInfo for SourceTag
    const questionSourceInfo = useMemo(() => {
      if (!question) return null;
      return questionToSourceInfo(question, question.level_question_num);
    }, [question]);

    // Handle click on SourceTag
    const handleSourceClick = useCallback(() => {
      if (document && updatePresentingDocument) {
        openDocument(document as OnyxDocument, updatePresentingDocument);
      } else if (question && openQuestion) {
        openQuestion(question);
      }
    }, [document, updatePresentingDocument, question, openQuestion]);

    if (value?.toString().startsWith("*")) {
      return <BlinkingDot addMargin />;
    } else if (value?.toString().startsWith("[")) {
      const sourceInfo = documentSourceInfo || questionSourceInfo;
      if (!sourceInfo) {
        return <>{rest.children}</>;
      }

      const displayName = document
        ? getDisplayNameForSource(document as OnyxDocument)
        : question?.question || "Question";

      return (
        <SourceTag
          inlineCitation
          displayName={displayName}
          sources={[sourceInfo]}
          onSourceClick={handleSourceClick}
          showDetailsCard
          className="mr-0.5"
        />
      );
    }

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

    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="cursor-pointer text-link hover:text-link-hover"
      >
        {rest.children}
      </a>
    );
  }
);

interface MemoizedParagraphProps {
  className?: string;
  children?: React.ReactNode;
}

export const MemoizedParagraph = memo(function MemoizedParagraph({
  className,
  children,
}: MemoizedParagraphProps) {
  return (
    <Text as="p" mainContentBody className={className}>
      {children}
    </Text>
  );
});

MemoizedAnchor.displayName = "MemoizedAnchor";
MemoizedLink.displayName = "MemoizedLink";
MemoizedParagraph.displayName = "MemoizedParagraph";
