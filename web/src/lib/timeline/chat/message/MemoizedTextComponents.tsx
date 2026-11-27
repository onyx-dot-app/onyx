import React, {
  memo,
  JSX,
  useMemo,
  useCallback,
  useContext,
  type MouseEvent,
} from "react";
import type { ExtraProps } from "react-markdown";
import { SourceIcon } from "@/components/SourceIcon";
import { WebResultIcon } from "@/components/WebResultIcon";
import { MinimalOnyxDocument, OnyxDocument } from "@/lib/search/types";
import { SubQuestionDetail, CitationMap } from "@/app/app/types";
import { ValidSources } from "@/lib/connectors/types/source";
import { ProjectFile } from "@/lib/projects/types";
import { Text, type TextColor, type TextFont } from "@opal/components";
import { richNodes } from "@opal/utils";
import SourceTag from "@/refresh-components/buttons/source-tag/SourceTag";
import {
  documentToSourceInfo,
  questionToSourceInfo,
  getDisplayNameForSource,
} from "@/refresh-components/buttons/source-tag/sourceTagUtils";
import { openDocument } from "@/lib/search/utils";
import { ensureHrefProtocol, isBareRelativeHref } from "@/lib/utils";
import { extractTextFromReactNode } from "@/lib/timeline/chat/message/codeUtils";
import { useTranslations } from "next-intl";
import { toast } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  type ChatArtifactFile,
  parseArtifactLink,
} from "@/lib/chat/publishedFiles";
import { PublishedFilesPanelContext } from "@/sections/chat/PublishedFileCards";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";

const CITATION_LABEL_PATTERN: RegExp = /^\[(D|Q)?\d+\]$/;

// The number of the newest artifact link click, across all links
let latestArtifactClick = 0;

// Returns the label only when it has no nested elements (e.g. bold).
function getPlainLabel(children: React.ReactNode): string | null {
  if (typeof children === "string" || typeof children === "number") {
    return String(children);
  }
  if (
    Array.isArray(children) &&
    children.every((c) => typeof c === "string" || typeof c === "number")
  ) {
    return children.join("");
  }
  return null;
}

interface DocumentCardProps {
  document: OnyxDocument;
  updatePresentingDocument: (document: MinimalOnyxDocument) => void;
  url?: string;
}
interface QuestionCardProps {
  question: SubQuestionDetail;
  openQuestion: (question: SubQuestionDetail) => void;
}

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
    updatePresentingDocument: (doc: MinimalOnyxDocument) => void;
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
            // Citation not resolved yet (data still streaming) — hide the
            // raw [[N]](url) link entirely. It will render as a chip once
            // the citation/document data arrives.
            return <></>;
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
                icon: icon,
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
  }: Partial<DocumentCardProps & QuestionCardProps> &
    ExtraProps & {
      href?: string;
      children?: React.ReactNode;
    }) => {
    const t = useTranslations("chat.messages");
    const value = rest.children;
    const panel = useContext(PublishedFilesPanelContext);

    // Convert document to SourceInfo for SourceTag
    const documentSourceInfo = useMemo(() => {
      if (!document) return null;
      return documentToSourceInfo(document);
    }, [document]);

    // Convert question to SourceInfo for SourceTag
    const questionSourceInfo = useMemo(() => {
      if (!question) return null;
      return questionToSourceInfo(question, question.level_question_num);
    }, [question]);

    // Handle click on SourceTag
    const handleSourceClick = useCallback(() => {
      if (document && updatePresentingDocument) {
        openDocument(document, updatePresentingDocument);
      } else if (question && openQuestion) {
        openQuestion(question);
      }
    }, [document, updatePresentingDocument, question, openQuestion]);

    const url: string | undefined = ensureHrefProtocol(href);
    // A VM path the model linked opens nothing in the browser.
    const isVmPath: boolean = !!url && isBareRelativeHref(url);
    const isChatFile: boolean = !!url?.includes("/api/chat/file/");
    const plainLabel: string | null = getPlainLabel(value);

    if (
      !isChatFile &&
      plainLabel !== null &&
      CITATION_LABEL_PATTERN.test(plainLabel)
    ) {
      const sourceInfo = documentSourceInfo || questionSourceInfo;
      // Find in chat skips citations: it searches the answer's own text.
      if (!sourceInfo) {
        return <span data-chat-find-ignore>{rest.children}</span>;
      }

      const displayName = document
        ? getDisplayNameForSource(document)
        : question?.question || t("memoizedLink.questionFallback.label");

      return (
        <span data-chat-find-ignore>
          <SourceTag
            variant="inlineCitation"
            displayName={displayName}
            sources={[sourceInfo]}
            onSourceClick={handleSourceClick}
            showDetailsCard
            className="me-0.5"
          />
        </span>
      );
    }

    if (isVmPath) {
      return <span>{rest.children}</span>;
    }

    if (isChatFile && updatePresentingDocument) {
      const fileId: string =
        url!.split("/api/chat/file/")[1]?.split(/[?#]/)[0] || "";
      const filename: string =
        extractTextFromReactNode(value).trim() || "download";
      return (
        <button
          type="button"
          onClick={() =>
            updatePresentingDocument({
              document_id: fileId,
              semantic_identifier: filename,
            })
          }
          // `inline`: a button is inline-block by default, which would break
          // the surrounding prose differently than the <a> it replaces.
          className="inline cursor-pointer underline underline-offset-2"
        >
          {rest.children}
        </button>
      );
    }

    // An artifact link opens its file in this chat's panel, pinned to the
    // version it names; a modified or middle click keeps the new tab, whose
    // page opens the owning chat.
    const artifactLink = url ? parseArtifactLink(url) : null;
    function openArtifact(event: MouseEvent<HTMLAnchorElement>) {
      if (
        !artifactLink ||
        !panel ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      event.preventDefault();
      const { version } = artifactLink;
      // Only the latest artifact click opens its file, and only while the
      // user stays in the chat it was made in
      const click = ++latestArtifactClick;
      const sessionId = useChatSessionStore.getState().currentSessionId;
      const stillLatest = () =>
        click === latestArtifactClick &&
        useChatSessionStore.getState().currentSessionId === sessionId;
      errorHandlingFetcher<ChatArtifactFile>(
        SWR_KEYS.chatArtifact(artifactLink.artifactId, version)
      ).then(
        (file) => {
          if (stillLatest()) panel.openFile(file, version !== null);
        },
        () => {
          if (stillLatest())
            toast.error(t("memoizedLink.artifactError.message"));
        }
      );
    }

    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        onClick={openArtifact}
        className="cursor-pointer underline underline-offset-2"
      >
        {rest.children}
      </a>
    );
  }
);

interface MemoizedParagraphProps {
  font?: TextFont;
  color?: TextColor;
  // Stamped per-paragraph by the rehypeDirection plugin so RTL and LTR
  // paragraphs align independently. Unstamped paragraphs inherit their
  // container's direction.
  dir?: React.HTMLAttributes<HTMLElement>["dir"];
  children?: React.ReactNode;
}

export const MemoizedParagraph = memo(function MemoizedParagraph({
  font = "main-content-body",
  color = "text-04",
  dir,
  children,
}: MemoizedParagraphProps) {
  return (
    <Text as="p" dir={dir} font={font} color={color}>
      {richNodes(children)}
    </Text>
  );
});

MemoizedAnchor.displayName = "MemoizedAnchor";
MemoizedLink.displayName = "MemoizedLink";
MemoizedParagraph.displayName = "MemoizedParagraph";
