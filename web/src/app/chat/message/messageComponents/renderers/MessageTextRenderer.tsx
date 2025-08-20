import React, { useCallback, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypePrism from "rehype-prism-plus";
import rehypeKatex from "rehype-katex";
import "prismjs/themes/prism-tomorrow.css";
import "katex/dist/katex.min.css";
import "../../custom-code-styles.css";

import { ChatPacket, PacketType } from "../../../services/streamingModels";
import { MessageRenderer, FullChatState } from "../interfaces";
import {
  MemoizedAnchor,
  MemoizedParagraph,
} from "../../MemoizedTextComponents";
import { extractCodeText, preprocessLaTeX } from "../../codeUtils";
import { CodeBlock } from "../../CodeBlock";
import { transformLinkUri } from "@/lib/utils";
import { isFinalAnswerComplete } from "../../../services/packetUtils";

// Control the rate of packet streaming (packets per second)
const PACKET_DELAY_MS = 10;

export const MessageTextRenderer: MessageRenderer<
  ChatPacket,
  FullChatState
> = ({ packets, state, onComplete, renderType, animate }) => {
  // If we're animating and the final answer is already complete, show more packets initially
  const initialPacketCount = animate
    ? packets.length > 0
      ? 1 // Otherwise start with 1 packet
      : 0
    : -1; // Show all if not animating

  const [displayedPacketCount, setDisplayedPacketCount] =
    useState(initialPacketCount);

  // Get the full content from all packets
  const fullContent = packets
    .map((packet) => {
      if (
        packet.obj.type === PacketType.MESSAGE_DELTA ||
        packet.obj.type === PacketType.MESSAGE_START
      ) {
        return packet.obj.content;
      }
      return "";
    })
    .join("");

  // Animation effect - gradually increase displayed packets at controlled rate
  useEffect(() => {
    if (!animate) {
      setDisplayedPacketCount(-1); // Show all packets
      return;
    }

    if (displayedPacketCount >= 0 && displayedPacketCount < packets.length) {
      const timer = setTimeout(() => {
        setDisplayedPacketCount((prev) => Math.min(prev + 1, packets.length));
      }, PACKET_DELAY_MS);

      return () => clearTimeout(timer);
    }
  }, [animate, displayedPacketCount, packets.length]);

  // Reset displayed count when packet array changes significantly (e.g., new message)
  useEffect(() => {
    if (animate && packets.length < displayedPacketCount) {
      const resetCount = isFinalAnswerComplete(packets)
        ? Math.min(10, packets.length)
        : packets.length > 0
          ? 1
          : 0;
      setDisplayedPacketCount(resetCount);
    }
  }, [animate, packets.length, displayedPacketCount]);

  // Only mark as complete when all packets are received AND displayed
  useEffect(() => {
    if (isFinalAnswerComplete(packets)) {
      // If animating, wait until all packets are displayed
      if (
        animate &&
        displayedPacketCount >= 0 &&
        displayedPacketCount < packets.length
      ) {
        return;
      }
      onComplete();
    }
  }, [packets, onComplete, animate, displayedPacketCount]);

  // Get content based on displayed packet count
  const content = useMemo(() => {
    if (!animate || displayedPacketCount === -1) {
      return fullContent; // Show all content
    }

    // Only show content from packets up to displayedPacketCount
    return packets
      .slice(0, displayedPacketCount)
      .map((packet) => {
        if (
          packet.obj.type === PacketType.MESSAGE_DELTA ||
          packet.obj.type === PacketType.MESSAGE_START
        ) {
          return packet.obj.content;
        }
        return "";
      })
      .join("");
  }, [animate, displayedPacketCount, fullContent, packets]);

  const processContent = (content: string) => {
    const codeBlockRegex = /```(\w*)\n[\s\S]*?```|```[\s\S]*?$/g;
    const matches = content.match(codeBlockRegex);

    if (matches) {
      content = matches.reduce((acc, match) => {
        if (!match.match(/```\w+/)) {
          return acc.replace(match, match.replace("```", "```plaintext"));
        }
        return acc;
      }, content);

      const lastMatch = matches[matches.length - 1];
      if (lastMatch && !lastMatch.endsWith("```")) {
        return preprocessLaTeX(content);
      }
    }

    const processed = preprocessLaTeX(content);
    return processed;
  };

  const processedContent = processContent(content);

  const paragraphCallback = useCallback(
    (props: any) => <MemoizedParagraph>{props.children}</MemoizedParagraph>,
    []
  );

  const anchorCallback = useCallback(
    (props: any) => (
      <MemoizedAnchor
        updatePresentingDocument={state.setPresentingDocument || (() => {})}
        docs={state.docs || []}
        userFiles={state.userFiles || []}
        href={props.href}
      >
        {props.children}
      </MemoizedAnchor>
    ),
    [state.docs, state.userFiles, state.setPresentingDocument]
  );

  const markdownComponents = useMemo(
    () => ({
      a: anchorCallback,
      p: paragraphCallback,
      b: ({ node, className, children }: any) => {
        return <span className={className}>{children}</span>;
      },
      code: ({ node, className, children }: any) => {
        const codeText = extractCodeText(node, processedContent, children);

        return (
          <CodeBlock className={className} codeText={codeText}>
            {children}
          </CodeBlock>
        );
      },
    }),
    [anchorCallback, paragraphCallback, processedContent]
  );

  return {
    icon: null,
    status: null,
    content: (
      <ReactMarkdown
        className="prose dark:prose-invert max-w-full text-base"
        components={markdownComponents}
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypePrism, { ignoreMissing: true }], rehypeKatex]}
        urlTransform={transformLinkUri}
      >
        {processedContent}
      </ReactMarkdown>
    ),
  };
};
