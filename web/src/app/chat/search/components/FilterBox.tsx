import React from "react";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
import { SourceMetadata } from "@/lib/search/interfaces";
import { SourceIcon } from "@/components/SourceIcon";
import { Badge } from "@/components/ui/badge";
import { Check, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface FilterBoxProps {
  label: string;
  icon?: React.ReactNode;
  contentComponent?: React.ReactNode;
  selected?: boolean;
  count?: number;
  onClick?: () => void;
}

export function FilterBox({
  label,
  icon,
  contentComponent,
  selected = false,
  count,
  onClick,
}: FilterBoxProps) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className={cn(
            "border border-gray-300  rounded-md px-4 py-2 h-auto flex items-center gap-2 text-sm font-medium transition-colors hover:bg-gray-50 w-[160px] justify-between",
            selected && "bg-gray-100 border-gray-400"
          )}
          onClick={onClick}
        >
          <div className="flex items-center gap-2">
            {icon}
            <span>{label}</span>
            {count !== undefined && (
              <Badge variant="secondary" className=" -my-1 -mr-4 ml-1 text-xs">
                {count}
              </Badge>
            )}
          </div>
          <ChevronDown className="h-4 w-4 opacity-50" />
        </Button>
      </PopoverTrigger>
      {contentComponent && (
        <PopoverContent
          className="w-64 p-0 max-h-[300px] overflow-y-auto"
          align="start"
        >
          {contentComponent}
        </PopoverContent>
      )}
    </Popover>
  );
}

// Source Filter Component
export function SourceFilter({
  sources,
  selectedSources,
  onSourceSelect,
}: {
  sources: SourceMetadata[];
  selectedSources: SourceMetadata[];
  onSourceSelect: (source: SourceMetadata) => void;
}) {
  const selectedSourceIds = selectedSources.map((s) => s.internalName);

  return (
    <div className="p-2 divide-y divide-gray-100">
      <div className="py-2 px-2 font-medium">Sources</div>
      <div>
        {sources.map((source) => (
          <div
            key={source.internalName}
            className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-gray-50"
            onClick={() => onSourceSelect(source)}
          >
            <div className="flex items-center gap-2">
              <SourceIcon sourceType={source.internalName} iconSize={16} />
              <span className="text-sm">{source.displayName}</span>
            </div>
            {selectedSourceIds.includes(source.internalName) && (
              <Check className="h-4 w-4 text-blue-600" />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// Time Filter Component
export function TimeFilter({
  onTimeSelect,
  selectedTimeRange,
}: {
  onTimeSelect: (
    range: { from: Date; to: Date; selectValue: string } | null
  ) => void;
  selectedTimeRange: { from: Date; to: Date; selectValue: string } | null;
}) {
  const timeOptions = [
    { label: "Any time", range: null },
    {
      label: "Past 24 hours",
      range: {
        from: new Date(Date.now() - 24 * 60 * 60 * 1000),
        to: new Date(),
        selectValue: "past_day",
      },
    },
    {
      label: "Past week",
      range: {
        from: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000),
        to: new Date(),
        selectValue: "past_week",
      },
    },
    {
      label: "Past month",
      range: {
        from: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000),
        to: new Date(),
        selectValue: "past_month",
      },
    },
    {
      label: "Past year",
      range: {
        from: new Date(Date.now() - 365 * 24 * 60 * 60 * 1000),
        to: new Date(),
        selectValue: "past_year",
      },
    },
  ];

  return (
    <div className="p-2 divide-y divide-gray-100">
      <div className="py-2 px-2 font-medium">Time Range</div>
      <div>
        {timeOptions.map((option) => (
          <div
            key={option.label}
            className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-gray-50"
            onClick={() => onTimeSelect(option.range)}
          >
            <span className="text-sm">{option.label}</span>
            {(!selectedTimeRange && !option.range) ||
            (selectedTimeRange &&
              option.range &&
              selectedTimeRange.from.getTime() ===
                option.range.from.getTime()) ? (
              <Check className="h-4 w-4 text-blue-600" />
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

// Author Filter Component
export function AuthorFilter({
  authors = [
    "John Doe",
    "Jane Smith",
    "Alex Johnson",
    "Maria Garcia",
    "Sam Lee",
  ],
  selectedAuthors = [],
  onAuthorSelect,
}: {
  authors?: string[];
  selectedAuthors?: string[];
  onAuthorSelect: (author: string) => void;
}) {
  return (
    <div className="p-2 divide-y divide-gray-100">
      <div className="py-2 px-2 font-medium">Authors</div>
      <div>
        {authors.map((author) => (
          <div
            key={author}
            className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-gray-50"
            onClick={() => onAuthorSelect(author)}
          >
            <span className="text-sm">{author}</span>
            {selectedAuthors.includes(author) && (
              <Check className="h-4 w-4 text-blue-600" />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
