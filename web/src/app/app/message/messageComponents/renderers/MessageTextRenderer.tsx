import React, { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown, { Components } from "react-markdown";
import type { PluggableList } from "unified";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

import { useTypewriter } from "@/hooks/useTypewriter";
import Text from "@/refresh-components/texts/Text";
import {
  ChatPacket,
  PacketType,
  StopReason,
} from "../../../services/streamingModels";
import { MessageRenderer, FullChatState } from "../interfaces";
import { isFinalAnswerComplete } from "../../../services/packetUtils";
import { processContent, ScrollableTable } from "../markdownUtils";
import { BlinkingBar } from "../../BlinkingBar";
import { useVoiceMode } from "@/providers/VoiceModeProvider";
import {
  MemoizedAnchor,
  MemoizedParagraph,
} from "@/app/app/message/MemoizedTextComponents";
import { extractCodeText } from "@/app/app/message/codeUtils";
import { CodeBlock } from "@/app/app/message/CodeBlock";
import { InMessageImage } from "@/app/app/components/files/images/InMessageImage";
import { extractChatImageFileId } from "@/app/app/components/files/images/utils";
import { cn, transformLinkUri } from "@/lib/utils";
import { useSmoothStreaming } from "@/hooks/useSmoothStreaming";

/** Maps a visible-char count to a markdown index (skips formatting chars,
 *  extends to word boundary). Used by the voice-sync reveal path only. */
function getRevealPosition(markdown: string, cleanChars: number): number {
  const skipChars = new Set(["*", "`", "#"]);
  let cleanIndex = 0;
  let mdIndex = 0;

  while (cleanIndex < cleanChars && mdIndex < markdown.length) {
    const char = markdown[mdIndex];

    if (char !== undefined && skipChars.has(char)) {
      mdIndex++;
      continue;
    }

    if (
      char === "]" &&
      mdIndex + 1 < markdown.length &&
      markdown[mdIndex + 1] === "("
    ) {
      const closeIdx = markdown.indexOf(")", mdIndex + 2);
      if (closeIdx > 0) {
        mdIndex = closeIdx + 1;
        continue;
      }
    }

    cleanIndex++;
    mdIndex++;
  }

  while (
    mdIndex < markdown.length &&
    markdown[mdIndex] !== " " &&
    markdown[mdIndex] !== "\n"
  ) {
    mdIndex++;
  }

  return mdIndex;
}

// Cheap streaming plugins (gfm only) → cheap per-frame parse. Full
// pipeline flips in once, at the end, for syntax highlighting + math.
const STREAMING_REMARK_PLUGINS: PluggableList = [remarkGfm];
const STREAMING_REHYPE_PLUGINS: PluggableList = [];
const FULL_REMARK_PLUGINS: PluggableList = [
  remarkGfm,
  [remarkMath, { singleDollarTextMath: true }],
];
const FULL_REHYPE_PLUGINS: PluggableList = [rehypeHighlight, rehypeKatex];

export const MessageTextRenderer: MessageRenderer<
  ChatPacket,
  FullChatState
> = ({
  packets,
  state,
  messageNodeId,
  hasTimelineThinking,
  onComplete,
  renderType,
  animate,
  stopPacketSeen,
  stopReason,
  children,
}) => {
  const { enabled: smoothStreamingEnabled } = useSmoothStreaming();

  const lastStableSyncedContentRef = useRef("");
  const lastVisibleContentRef = useRef("");

  // Timeout guard: if TTS doesn't start within 5s of voice sync
  // activating, fall back to normal streaming. Prevents permanent
  // content suppression when the voice WebSocket fails to connect.
  const [voiceSyncTimedOut, setVoiceSyncTimedOut] = useState(false);
  const voiceSyncTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  );

  const {
    revealedCharCount,
    autoPlayback,
    isAudioSyncActive,
    activeMessageNodeId,
    isAwaitingAutoPlaybackStart,
  } = useVoiceMode();

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

  const shouldUseAutoPlaybackSync =
    autoPlayback &&
    !voiceSyncTimedOut &&
    typeof messageNodeId === "number" &&
    activeMessageNodeId === messageNodeId;

  // Start/clear the timeout when voice sync activates/deactivates.
  useEffect(() => {
    if (shouldUseAutoPlaybackSync && isAwaitingAutoPlaybackStart) {
      if (!voiceSyncTimeoutRef.current) {
        voiceSyncTimeoutRef.current = setTimeout(() => {
          setVoiceSyncTimedOut(true);
        }, 5000);
      }
    } else {
      // TTS started or sync deactivated — clear timeout
      if (voiceSyncTimeoutRef.current) {
        clearTimeout(voiceSyncTimeoutRef.current);
        voiceSyncTimeoutRef.current = null;
      }
      if (voiceSyncTimedOut && !autoPlayback) setVoiceSyncTimedOut(false);
    }
    return () => {
      if (voiceSyncTimeoutRef.current) {
        clearTimeout(voiceSyncTimeoutRef.current);
        voiceSyncTimeoutRef.current = null;
      }
    };
  }, [
    shouldUseAutoPlaybackSync,
    isAwaitingAutoPlaybackStart,
    isAudioSyncActive,
    voiceSyncTimedOut,
  ]);

  // Normal streaming hands full text to the typewriter. Voice-sync
  // paths pre-slice and bypass. If shouldUseAutoPlaybackSync is false
  // (including after the 5s timeout), all paths fall through to fullContent.
  const computedContent = useMemo(() => {
    if (shouldUseAutoPlaybackSync && isAwaitingAutoPlaybackStart) {
      return "";
    }

    if (shouldUseAutoPlaybackSync && isAudioSyncActive) {
      const MIN_REVEAL_CHARS = 12;
      if (revealedCharCount < MIN_REVEAL_CHARS) {
        return "";
      }
      const revealPos = getRevealPosition(fullContent, revealedCharCount);
      return fullContent.slice(0, Math.max(revealPos, 0));
    }

    if (shouldUseAutoPlaybackSync && !stopPacketSeen) {
      return lastStableSyncedContentRef.current;
    }

    return fullContent;
  }, [
    shouldUseAutoPlaybackSync,
    isAwaitingAutoPlaybackStart,
    isAudioSyncActive,
    revealedCharCount,
    fullContent,
    stopPacketSeen,
  ]);

  // Monotonic guard for voice sync + freeze on user cancel.
  const content = useMemo(() => {
    const wasUserCancelled = stopReason === StopReason.USER_CANCELLED;

    if (wasUserCancelled && animate) {
      return lastVisibleContentRef.current;
    }

    if (!shouldUseAutoPlaybackSync) {
      return computedContent;
    }

    if (computedContent.length === 0) {
      return lastStableSyncedContentRef.current;
    }

    const last = lastStableSyncedContentRef.current;
    if (computedContent.startsWith(last)) {
      return computedContent;
    }

    if (!stopPacketSeen || wasUserCancelled) {
      return last;
    }

    return computedContent;
  }, [
    computedContent,
    shouldUseAutoPlaybackSync,
    stopPacketSeen,
    stopReason,
    animate,
  ]);

  useEffect(() => {
    if (stopReason === StopReason.USER_CANCELLED) {
      return;
    }
    if (!shouldUseAutoPlaybackSync) {
      lastStableSyncedContentRef.current = "";
    } else if (content.length > 0) {
      lastStableSyncedContentRef.current = content;
    }
  }, [content, shouldUseAutoPlaybackSync, stopReason]);

  useEffect(() => {
    if (content.length > 0) {
      lastVisibleContentRef.current = content;
    }
  }, [content]);

  const isStreamingAnimationEnabled =
    animate &&
    !shouldUseAutoPlaybackSync &&
    stopReason !== StopReason.USER_CANCELLED &&
    smoothStreamingEnabled;

  const isStreamFinished = isFinalAnswerComplete(packets);

  const displayedContent = useTypewriter(content, isStreamingAnimationEnabled);

  // One-way signal: stream done AND typewriter caught up. Do NOT derive
  // this from "typewriter currently behind" — it oscillates mid-stream
  // between packet bursts and would thrash the plugin pipeline.
  const streamFullyDisplayed =
    isStreamFinished && displayedContent.length >= content.length;

  // Fire onComplete exactly once per mount. `onComplete` is an inline
  // arrow in AgentMessage so its identity changes on every parent render;
  // without this guard, each new identity would re-fire the effect once
  // `streamFullyDisplayed` is true.
  const onCompleteFiredRef = useRef(false);
  useEffect(() => {
    if (streamFullyDisplayed && !onCompleteFiredRef.current) {
      onCompleteFiredRef.current = true;
      onComplete();
    }
  }, [streamFullyDisplayed, onComplete]);

  const processedContent = useMemo(
    () => processContent(displayedContent),
    [displayedContent]
  );

  // Stable-identity components for ReactMarkdown. Dynamic data (`state`,
  // `processedContent`) flows through refs so the callback identities
  // never change — otherwise every typewriter tick would invalidate
  // React reconciliation on the markdown subtree.
  const stateRef = useRef(state);
  stateRef.current = state;
  const processedContentRef = useRef(processedContent);
  processedContentRef.current = processedContent;

  const markdownComponents = useMemo<Components>(
    () => ({
      a: ({ href, children }) => {
        const s = stateRef.current;
        const imageFileId = extractChatImageFileId(
          href,
          String(children ?? "")
        );
        if (imageFileId) {
          return (
            <InMessageImage
              fileId={imageFileId}
              fileName={String(children ?? "")}
            />
          );
        }
        return (
          <MemoizedAnchor
            updatePresentingDocument={s?.setPresentingDocument || (() => {})}
            docs={s?.docs || []}
            userFiles={s?.userFiles || []}
            citations={s?.citations}
            href={href}
          >
            {children}
          </MemoizedAnchor>
        );
      },
      p: ({ children }) => (
        <MemoizedParagraph className="font-main-content-body">
          {children}
        </MemoizedParagraph>
      ),
      pre: ({ children }) => <>{children}</>,
      b: ({ className, children }) => (
        <span className={className}>{children}</span>
      ),
      ul: ({ className, children, ...rest }) => (
        <ul className={className} {...rest}>
          {children}
        </ul>
      ),
      ol: ({ className, children, ...rest }) => (
        <ol className={className} {...rest}>
          {children}
        </ol>
      ),
      li: ({ className, children, ...rest }) => (
        <li className={className} {...rest}>
          {children}
        </li>
      ),
      table: ({ className, children, ...rest }) => (
        <ScrollableTable className={className} {...rest}>
          {children}
        </ScrollableTable>
      ),
      code: ({ node, className, children }) => {
        const codeText = extractCodeText(
          node,
          processedContentRef.current,
          children
        );
        return (
          <CodeBlock className={className} codeText={codeText}>
            {children}
          </CodeBlock>
        );
      },
    }),
    []
  );

  const shouldShowThinkingPlaceholder =
    shouldUseAutoPlaybackSync &&
    isAwaitingAutoPlaybackStart &&
    !hasTimelineThinking &&
    !stopPacketSeen;

  const shouldShowSpeechWarmupIndicator =
    shouldUseAutoPlaybackSync &&
    !isAwaitingAutoPlaybackStart &&
    content.length === 0 &&
    fullContent.length > 0 &&
    !hasTimelineThinking &&
    !stopPacketSeen;

  const shouldShowCursor =
    displayedContent.length > 0 &&
    ((isStreamingAnimationEnabled && !streamFullyDisplayed) ||
      (!isStreamingAnimationEnabled && !stopPacketSeen) ||
      (shouldUseAutoPlaybackSync && content.length < fullContent.length));

  // `[*]() ` is rendered by the anchor component as an inline blinking
  // caret, keeping it flush with the trailing character.
  const markdownInput = shouldShowCursor
    ? processedContent + " [*]() "
    : processedContent;

  return children([
    {
      icon: null,
      status: null,
      content:
        shouldShowThinkingPlaceholder || shouldShowSpeechWarmupIndicator ? (
          <Text as="span" secondaryBody text04 className="italic">
            Thinking
          </Text>
        ) : displayedContent.length > 0 ? (
          <div dir="auto">
            <ReactMarkdown
              className="prose prose-onyx font-main-content-body max-w-full"
              components={markdownComponents}
              remarkPlugins={
                streamFullyDisplayed
                  ? FULL_REMARK_PLUGINS
                  : STREAMING_REMARK_PLUGINS
              }
              rehypePlugins={
                streamFullyDisplayed
                  ? FULL_REHYPE_PLUGINS
                  : STREAMING_REHYPE_PLUGINS
              }
              urlTransform={transformLinkUri}
            >
              {markdownInput}
            </ReactMarkdown>
          </div>
        ) : (
          <BlinkingBar addMargin />
        ),
    },
  ]);
};
