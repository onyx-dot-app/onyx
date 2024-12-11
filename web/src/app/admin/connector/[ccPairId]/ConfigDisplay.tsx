import CardSection from "@/components/admin/CardSection";
import { getNameFromPath } from "@/lib/fileUtils";
import { ValidSources } from "@/lib/types";
import Title from "@/components/ui/title";
import { EditIcon } from "@/components/icons/icons";

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

function buildConfigEntries(
  obj: any,
  sourceType: ValidSources
): { [key: string]: string } {
  if (sourceType === ValidSources.File) {
    return obj.file_locations
      ? {
          file_names: obj.file_locations.map(getNameFromPath),
        }
      : {};
  } else if (sourceType === ValidSources.GoogleSites) {
    return {
      base_url: obj.base_url,
    };
  }
  return obj;
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
    const minutes = Math.round(seconds / 60);
    return `${minutes} minute${minutes !== 1 ? "s" : ""}`;
  };
  const formatPruneFrequency = (seconds: number | null): string => {
    if (seconds === null) return "-";
    const days = Math.round(seconds / (60 * 60 * 24));
    return `${days} day${days !== 1 ? "s" : ""}`;
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
    <>
      <Title className="mt-8 mb-2">Advanced Configuration</Title>
      <CardSection>
        <ul className="w-full text-sm divide-y divide-neutral-200 dark:divide-neutral-700">
          {pruneFreq && (
            <li
              key={0}
              className="w-full flex justify-between items-center py-2"
            >
              <span>Pruning Frequency</span>
              <span className="ml-auto w-24">
                {formatPruneFrequency(pruneFreq)}
              </span>
              <span className="w-8 text-right">
                <button onClick={() => onPruningEdit()}>
                  <EditIcon size={12} />
                </button>
              </span>
            </li>
          )}
          {refreshFreq && (
            <li
              key={1}
              className="w-full flex justify-between items-center py-2"
            >
              <span>Refresh Frequency</span>
              <span className="ml-auto w-24">
                {formatRefreshFrequency(refreshFreq)}
              </span>
              <span className="w-8 text-right">
                <button onClick={() => onRefreshEdit()}>
                  <EditIcon size={12} />
                </button>
              </span>
            </li>
          )}
          {indexingStart && (
            <li
              key={2}
              className="w-full flex justify-between items-center py-2"
            >
              <span>Indexing Start</span>
              <span>{formatDate(indexingStart)}</span>
            </li>
          )}
        </ul>
      </CardSection>
    </>
  );
}

export function ConfigDisplay({
  connectorSpecificConfig,
  sourceType,
}: {
  connectorSpecificConfig: any;
  sourceType: ValidSources;
}) {
  const configEntries = Object.entries(
    buildConfigEntries(connectorSpecificConfig, sourceType)
  );
  if (!configEntries.length) {
    return null;
  }

  return (
    <>
      <Title className="mb-2">Configuration</Title>
      <CardSection>
        <ul className="w-full text-sm divide-y divide-neutral-200 dark:divide-neutral-700">
          {configEntries.map(([key, value]) => (
            <li
              key={key}
              className="w-full flex justify-between items-center py-2"
            >
              <span>{key}</span>
              <span>{convertObjectToString(value) || "-"}</span>
            </li>
          ))}
        </ul>
      </CardSection>
    </>
  );
}
