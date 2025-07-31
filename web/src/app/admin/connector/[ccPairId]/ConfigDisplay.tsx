import { ValidSources } from "@/lib/types";
import { EditIcon } from "@/components/icons/icons";

import { useState } from "react";
import { ChevronUpIcon } from "lucide-react";
import { ChevronDownIcon } from "@/components/icons/icons";

function convertObjectToString(obj: any): string | any {
  // Check if obj is an object and not an array or null
  if (typeof obj === "object" && obj !== null) {
    if (!Array.isArray(obj)) {
      return JSON.stringify(obj);
    } else {
      if (obj.length === 0) {
        return null;
      }
      return obj.map((item) => convertObjectToString(item)).join(", ");
    }
  }
  if (typeof obj === "boolean") {
    return obj.toString();
  }
  return obj;
}

export function buildConfigEntries(
  obj: any,
  sourceType: ValidSources
): { [key: string]: string } {
  if (sourceType === ValidSources.File) {
    return obj.file_names
      ? {
          file_names: obj.file_names,
        }
      : {
          // For deployments that don't run file_names migration
          file_locations: obj.file_locations,
        };
  } else if (sourceType === ValidSources.GoogleSites) {
    return {
      base_url: obj.base_url,
    };
  }
  return obj;
}

function ConfigItem({
  label,
  value,
  onEdit,
}: {
  label: string;
  value: any;
  onEdit?: () => void;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const isExpandable = Array.isArray(value) && value.length > 5;

  const renderValue = () => {
    if (Array.isArray(value)) {
      const displayedItems = isExpanded ? value : value.slice(0, 5);
      return (
        <ul className="list-disc pl-4 overflow-x-auto">
          {displayedItems.map((item, index) => (
            <li
              key={index}
              className="mb-1 overflow-hidden text-ellipsis whitespace-nowrap"
            >
              {convertObjectToString(item)}
            </li>
          ))}
        </ul>
      );
    } else if (typeof value === "object" && value !== null) {
      return (
        <div className="overflow-x-auto">
          {Object.entries(value).map(([key, val]) => (
            <div key={key} className="mb-1">
              <span className="font-semibold">{key}:</span>{" "}
              {convertObjectToString(val)}
            </div>
          ))}
        </div>
      );
    }
    // TODO: figure out a nice way to display boolean values
    else if (typeof value === "boolean") {
      return value ? "True" : "False";
    }
    return convertObjectToString(value) || "-";
  };

  return (
    <li className="w-full py-4 px-1">
      <div className="flex items-center w-full">
        <span className="text-sm">{label}</span>
        <div className="text-right overflow-x-auto max-w-[60%] text-sm font-normal ml-auto">
          {renderValue()}

          {isExpandable && (
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="mt-2 text-sm text-text-600 hover:text-text-800 flex items-center ml-auto"
            >
              {isExpanded ? (
                <>
                  <ChevronUpIcon className="h-4 w-4 mr-1" />
                  Show less
                </>
              ) : (
                <>
                  <ChevronDownIcon className="h-4 w-4 mr-1" />
                  Show all ({value.length} items)
                </>
              )}
            </button>
          )}
        </div>
        {onEdit && (
          <button onClick={onEdit} className="ml-4">
            <EditIcon size={12} />
          </button>
        )}
      </div>
    </li>
  );
}

export function AdvancedConfigDisplay({
  pruneFreq,
  refreshFreq,
  indexingStart,
  onRefreshEdit,
  onPruningEdit,
}: {
  pruneFreq: number | null;
  refreshFreq: number | null;
  indexingStart: Date | null;
  onRefreshEdit: () => void;
  onPruningEdit: () => void;
}) {
  const formatRefreshFrequency = (seconds: number | null): string => {
    if (seconds === null) return "-";
    const totalMinutes = seconds / 60;

    // If it's 60 minutes or more and evenly divisible by 60, show in hours
    if (totalMinutes >= 60 && totalMinutes % 60 === 0) {
      const hours = totalMinutes / 60;
      return `${hours} hour${hours !== 1 ? "s" : ""}`;
    }

    // Otherwise show in minutes
    const minutes = Math.round(totalMinutes);
    return `${minutes} minute${minutes !== 1 ? "s" : ""}`;
  };
  const formatPruneFrequency = (seconds: number | null): string => {
    if (seconds === null) return "-";
    const totalHours = seconds / 3600;

    // If less than 1 hour, show in minutes
    if (totalHours < 1) {
      const minutes = Math.round(seconds / 60);
      return `${minutes} minute${minutes !== 1 ? "s" : ""}`;
    }

    const hours = Math.round(totalHours);

    // If it's 24 hours or more and evenly divisible by 24, show in days
    if (hours >= 24 && hours % 24 === 0) {
      const days = hours / 24;
      return `${days} day${days !== 1 ? "s" : ""}`;
    }

    // Otherwise show in hours
    return `${hours} hour${hours !== 1 ? "s" : ""}`;
  };

  const formatDate = (date: Date | null): string => {
    if (date === null) return "-";
    return date.toLocaleString("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZoneName: "short",
    });
  };

  return (
    <div>
      <ul className="w-full divide-y divide-neutral-200 dark:divide-neutral-700">
        {pruneFreq !== null && (
          <ConfigItem
            label="Pruning Frequency"
            value={formatPruneFrequency(pruneFreq)}
            onEdit={onPruningEdit}
          />
        )}
        {refreshFreq && (
          <ConfigItem
            label="Refresh Frequency"
            value={formatRefreshFrequency(refreshFreq)}
            onEdit={onRefreshEdit}
          />
        )}
        {indexingStart && (
          <ConfigItem
            label="Indexing Start"
            value={formatDate(indexingStart)}
          />
        )}
      </ul>
    </div>
  );
}

export function ConfigDisplay({
  configEntries,
  onEdit,
}: {
  configEntries: { [key: string]: string };
  onEdit?: (key: string) => void;
}) {
  return (
    <ul className="w-full divide-y divide-background-200 dark:divide-background-700">
      {Object.entries(configEntries).map(([key, value]) => (
        <ConfigItem
          key={key}
          label={key}
          value={value}
          onEdit={onEdit ? () => onEdit(key) : undefined}
        />
      ))}
    </ul>
  );
}
