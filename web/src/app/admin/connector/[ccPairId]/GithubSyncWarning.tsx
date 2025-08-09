"use client";

import React, { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ChevronDownIcon,
  ChevronUpIcon,
  CopyIcon,
  CheckIcon,
} from "lucide-react";

interface GithubSyncWarningProps {
  usernames: string[];
}

const INITIAL_DISPLAY_COUNT = 8;

export const GithubSyncWarning: React.FC<GithubSyncWarningProps> = ({
  usernames,
}) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isCopied, setIsCopied] = useState(false);

  if (!usernames || usernames.length === 0) {
    return null;
  }

  const hasMoreUsers = usernames.length > INITIAL_DISPLAY_COUNT;
  const displayedUsernames = isExpanded
    ? usernames
    : usernames.slice(0, INITIAL_DISPLAY_COUNT);
  const remainingCount = usernames.length - INITIAL_DISPLAY_COUNT;

  const handleCopyUsernames = async () => {
    try {
      await navigator.clipboard.writeText(usernames.join(", "));
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy usernames:", err);
    }
  };

  return (
    <div className="relative border-l-4 border-amber-300 bg-amber-50 dark:border-amber-700 dark:bg-amber-900/30 p-4 rounded-r-md">
      <Button
        variant="outline"
        size="sm"
        onClick={handleCopyUsernames}
        className={`absolute top-2 right-2 h-8 w-8 p-0 border-amber-400 dark:border-amber-600 hover:bg-amber-100 dark:hover:bg-amber-800/50 transition-all duration-200 ${
          isCopied
            ? "scale-110 bg-green-100 dark:bg-green-800/50 border-green-300 dark:border-green-600"
            : "hover:scale-105"
        }`}
      >
        {isCopied ? (
          <CheckIcon className="w-4 h-4 text-green-700 dark:text-green-200 animate-bounce" />
        ) : (
          <CopyIcon className="w-4 h-4 text-amber-700 dark:text-amber-200 transition-transform duration-200 hover:scale-110" />
        )}
      </Button>

      <div className="text-amber-700 dark:text-amber-200 text-sm mb-3 pr-12">
        The following usernames have not made their email addresses public on
        their GitHub profiles. Access to documents is granted via email—without
        it, users will not be able to access non-public repositories. Please ask
        them to update their profiles accordingly.
      </div>

      <div className="flex flex-wrap gap-2 mb-3">
        {displayedUsernames.map((username, index) => (
          <Badge
            key={index}
            variant="outline"
            className="bg-amber-50 dark:bg-amber-700/20 border-amber-300 dark:border-amber-600 text-amber-800 dark:text-amber-200 text-xs"
          >
            {username}
          </Badge>
        ))}
      </div>

      {hasMoreUsers && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setIsExpanded(!isExpanded)}
          className="text-amber-700 dark:text-amber-200 hover:text-amber-800 dark:hover:text-amber-100 hover:bg-amber-100 dark:hover:bg-amber-800/50 px-2 py-1 h-auto text-xs"
        >
          {isExpanded ? (
            <>
              <ChevronUpIcon className="w-3 h-3 mr-1" />
              View less
            </>
          ) : (
            <>
              <ChevronDownIcon className="w-3 h-3 mr-1" />
              View more ({remainingCount} remaining)
            </>
          )}
        </Button>
      )}
    </div>
  );
};
