"use client";

import React, { memo } from "react";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import {
  SvgArrowLeft,
  SvgArrowRight,
  SvgUser,
  SvgQuestionMarkSmall,
} from "@opal/icons";
import { SourceIcon } from "@/components/SourceIcon";
import { WebResultIcon } from "@/components/WebResultIcon";
import { ValidSources } from "@/lib/types";
import { timeAgo } from "@/lib/time";
import { IconProps } from "@/components/icons/icons";
import { SubQuestionDetail } from "@/app/app/interfaces";

export interface SourceInfo {
  id: string;
  title: string;
  sourceType: ValidSources;
  sourceUrl?: string;
  description?: string;
  metadata?: {
    author?: string;
    date?: string | Date;
    tags?: string[];
  };
  icon?: React.FunctionComponent<IconProps>;
  // Support for questions
  isQuestion?: boolean;
  questionData?: SubQuestionDetail;
}

interface SourceTagDetailsCardProps {
  sources: SourceInfo[];
  currentIndex: number;
  onPrev: () => void;
  onNext: () => void;
}

interface MetadataChipProps {
  icon?: React.FunctionComponent<IconProps>;
  text: string;
}

const MetadataChip = memo(function MetadataChip({
  icon: Icon,
  text,
}: MetadataChipProps) {
  return (
    <div className="flex items-center gap-0 bg-background-tint-02 rounded-08 p-1">
      {Icon && (
        <div className="flex items-center justify-center p-0.5 w-4 h-4">
          <Icon className="w-3 h-3 stroke-text-03" />
        </div>
      )}

      <Text secondaryBody text03 className="px-0.5 max-w-[10rem] truncate">
        {text}
      </Text>
    </div>
  );
});

const SourceTagDetailsCardInner = ({
  sources,
  currentIndex,
  onPrev,
  onNext,
}: SourceTagDetailsCardProps) => {
  const currentSource = sources[currentIndex];
  if (!currentSource) return null;

  const showNavigation = sources.length > 1;
  const isFirst = currentIndex === 0;
  const isLast = currentIndex === sources.length - 1;
  const isWebSource = currentSource.sourceType === "web";
  const isQuestion = currentSource.isQuestion;
  const relativeDate = timeAgo(
    currentSource.metadata?.date instanceof Date
      ? currentSource.metadata.date.toISOString()
      : currentSource.metadata?.date
  );

  return (
    <div className="w-[17.5rem] bg-background-neutral-00 border border-border-01 rounded-12 shadow-01 overflow-hidden">
      {/* Navigation header - only shown for multiple sources */}
      {showNavigation && (
        <div className="flex items-center justify-between p-2 bg-background-tint-01 border-b border-border-01">
          <div className="flex items-center gap-1">
            <IconButton
              main
              internal
              icon={SvgArrowLeft}
              onClick={onPrev}
              disabled={isFirst}
              className="!p-0.5"
            />
            <IconButton
              main
              internal
              icon={SvgArrowRight}
              onClick={onNext}
              disabled={isLast}
              className="!p-0.5"
            />
          </div>
          <Text secondaryBody text03 className="px-1">
            {currentIndex + 1}/{sources.length}
          </Text>
        </div>
      )}

      <div className="p-1 flex flex-col gap-1">
        {/* Header with icon and title */}
        <div className="flex items-start gap-1 p-0.5 min-h-[1.75rem] w-full text-left hover:bg-background-tint-01 rounded-08 transition-colors">
          <div className="flex items-center justify-center p-0.5 shrink-0 w-5 h-5">
            {isQuestion ? (
              <SvgQuestionMarkSmall size={16} className="text-text-03" />
            ) : currentSource.icon ? (
              <currentSource.icon size={16} />
            ) : isWebSource && currentSource.sourceUrl ? (
              <WebResultIcon url={currentSource.sourceUrl} size={16} />
            ) : (
              <SourceIcon
                sourceType={
                  currentSource.sourceType === "web"
                    ? ValidSources.Web
                    : currentSource.sourceType
                }
                iconSize={16}
              />
            )}
          </div>
          <div className="flex-1 min-w-0 px-0.5">
            <Text
              mainUiAction
              text04
              className="truncate w-full block leading-5"
            >
              {currentSource.title}
            </Text>
          </div>
        </div>

        {/* Metadata row */}
        {(currentSource.metadata?.author ||
          currentSource.metadata?.tags?.length ||
          relativeDate) && (
          <div className="flex flex-row items-center gap-2 ">
            <div className="flex flex-wrap gap-1 items-center">
              {currentSource.metadata?.author && (
                <MetadataChip
                  icon={SvgUser}
                  text={currentSource.metadata.author}
                />
              )}
              {currentSource.metadata?.tags
                ?.slice(0, 2)
                .map((tag) => <MetadataChip key={tag} text={tag} />)}
              {relativeDate && (
                <Text secondaryBody text02>
                  {relativeDate}
                </Text>
              )}
            </div>
          </div>
        )}

        {/* Description */}
        {currentSource.description && (
          <div className="px-1.5 pb-1">
            <Text secondaryBody text03 as="span" className="line-clamp-4">
              {currentSource.description}
            </Text>
          </div>
        )}
      </div>
    </div>
  );
};

const SourceTagDetailsCard = memo(SourceTagDetailsCardInner);
export default SourceTagDetailsCard;
