import {
  Citation,
  QuestionCardProps,
  DocumentCardProps,
} from "@/components/search/results/Citation";
import { LoadedOnyxDocument, OnyxDocument } from "@/lib/search/interfaces";
import React, { memo, JSX } from "react";
import { SourceIcon } from "@/components/SourceIcon";
import { WebResultIcon } from "@/components/WebResultIcon";
import { SubQuestionDetail, CitationMap } from "../interfaces";
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
    const isCitationFormat = value?.startsWith("[") && value?.endsWith("]");
    const match = (isCitationFormat && value) ? value.match(/\[(D|Q)?(\d+)\]/) : null;

    const match_item = match ? match[2] : undefined;
    const isSubQuestion = match ? match[1] === "Q" : false;
    const isDocument = match ? !isSubQuestion : false;
    const citation_num = match_item ? parseInt(match_item, 10) : -1;

    const associatedDoc = useMemo(() => {
      if (isDocument && docs && citations && citation_num !== -1) {
        const document_id = citations[citation_num];
        if (document_id) {
          return docs.find((d) => d.document_id === document_id) || null;
        }
      }
      return null;
    }, [isDocument, docs, citations, citation_num]);

    const associatedSubQuestion = useMemo(() => {
      return isSubQuestion && citation_num !== -1
        ? subQuestions?.[citation_num - 1]
        : undefined;
    }, [isSubQuestion, citation_num, subQuestions]);

    const associatedDocInfo = useMemo(() => {
      if (!associatedDoc) return undefined;

      let icon: React.ReactNode = null;
      if (associatedDoc.source_type === "web") {
        icon = <WebResultIcon url={associatedDoc.link} />;
      } else {
        icon = (
          <SourceIcon
            sourceType={associatedDoc.source_type as ValidSources}
            iconSize={18}
          />
        );
      }

      return {
        ...associatedDoc,
        icon: icon as any,
        link: associatedDoc.link,
      };
    }, [associatedDoc]);

    if (match) {
      if (!associatedDoc && !associatedSubQuestion) {
        return <>{children}</>;
      }

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
    const questionCardProps: QuestionCardProps | undefined = useMemo(
      () =>
        question && openQuestion
          ? {
            question: question,
            openQuestion: openQuestion,
          }
          : undefined,
      [question?.level, question?.level_question_num, openQuestion]
    );

    const documentCardProps: DocumentCardProps | undefined = useMemo(
      () =>
        document && updatePresentingDocument
          ? {
            url: document.link,
            document: document as LoadedOnyxDocument,
            updatePresentingDocument: updatePresentingDocument!,
          }
          : undefined,
      [document?.document_id, document?.link, updatePresentingDocument]
    );

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
