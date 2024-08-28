import { getNameFromPath } from "@/lib/fileUtils";
import { ValidSources } from "@/lib/types";
import { List, ListItem, Card, Title } from "@tremor/react";

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
  if (sourceType === "file") {
    return obj.file_locations
      ? {
          file_names: obj.file_locations.map(getNameFromPath),
        }
      : {};
  } else if (sourceType === "google_sites") {
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
}: {
  pruneFreq: number | null;
  refreshFreq: number | null;
  indexingStart: Date | null;
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
      <Card>
        <List>
          {pruneFreq && (
            <ListItem key={0}>
              <span>Pruning Frequency</span>
              <span>{formatPruneFrequency(pruneFreq)}</span>
            </ListItem>
          )}
          {refreshFreq && (
            <ListItem key={1}>
              <span>Refresh Frequency</span>
              <span>{formatRefreshFrequency(refreshFreq)}</span>
            </ListItem>
          )}
          {indexingStart && (
            <ListItem key={2}>
              <span>Indexing Start</span>
              <span>{formatDate(indexingStart)}</span>
            </ListItem>
          )}
        </List>
      </Card>
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
      <Card>
        <List>
          {configEntries.map(([key, value]) => (
            <ListItem key={key}>
              <span>{key}</span>
              <span>{convertObjectToString(value) || "-"}</span>
            </ListItem>
          ))}
        </List>
      </Card>
    </>
  );
}
