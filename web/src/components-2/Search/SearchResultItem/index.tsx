import React from "react";
import { SavedSearchDoc } from "@/app/search/interfaces";
import { getSourceMetadata } from "@/lib/sources";
import { timeAgo } from "@/lib/time";
import Markdown from "react-markdown";

interface SearchResultItemProps {
  doc: SavedSearchDoc;
  isSelected?: boolean;
  onClick?: () => void;
}

export default function SearchResultItem({
  doc,
  onClick,
}: SearchResultItemProps) {
  const sourceMetadata = getSourceMetadata(doc.source_type);
  const SourceIcon = sourceMetadata.icon;

  return (
    <div
      className={`
        rounded-lg
        p-4
        cursor-pointer
        transition-all
        duration-200
        hover:bg-neutral-100
        dark:hover:bg-neutral-800
      `}
      onClick={onClick}
    >
      {/* Header with source icon, title, and score */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex-1 min-w-0">
          {/* First line: Icon and Title */}
          <div className="flex items-center gap-3 mb-1">
            <div className="flex-shrink-0">
              <SourceIcon size={20} />
            </div>
            <h3 className="text-lg font-medium text-neutral-900 dark:text-neutral-100 truncate">
              {doc.semantic_identifier}
            </h3>
          </div>

          {/* Second line: Primary owners and date */}
          <div className="flex items-center gap-2 text-sm text-neutral-500 dark:text-neutral-400">
            {doc.primary_owners && doc.primary_owners.length > 0 && (
              <div className="flex items-center gap-1">
                {doc.primary_owners.map((owner, index) => (
                  <span
                    key={index}
                    className="bg-neutral-200 dark:bg-neutral-700 rounded-md px-3 py-1 text-xs"
                  >
                    {owner}
                  </span>
                ))}
              </div>
            )}
            {doc.updated_at && (
              <span className="text-neutral-400">
                {timeAgo(doc.updated_at)}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Content preview */}
      <p className="text-sm line-clamp-3 text-neutral-500 dark:text-neutral-400">
        <Markdown>{doc.blurb}</Markdown>
      </p>
    </div>
  );
}
