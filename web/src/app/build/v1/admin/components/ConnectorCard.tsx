"use client";

import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";
import { SourceIcon } from "@/components/SourceIcon";
import { ValidSources } from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";
import { SvgSettings } from "@opal/icons";

export type ConnectorStatus =
  | "not_connected"
  | "connected"
  | "indexing"
  | "error";

export interface BuildConnectorConfig {
  cc_pair_id: number;
  source: string;
  name: string;
  status: ConnectorStatus;
  docs_indexed: number;
  last_indexed: string | null;
  error_message?: string | null;
}

interface ConnectorCardProps {
  connectorType: ValidSources;
  config: BuildConnectorConfig | null;
  onConfigure: () => void;
}

function getStatusIndicator(status: ConnectorStatus) {
  switch (status) {
    case "connected":
      return <div className="w-2 h-2 rounded-full bg-green-500" />;
    case "indexing":
      return (
        <div className="w-2 h-2 rounded-full bg-yellow-500 animate-pulse" />
      );
    case "error":
      return <div className="w-2 h-2 rounded-full bg-red-500" />;
    case "not_connected":
    default:
      return <div className="w-2 h-2 rounded-full bg-gray-400" />;
  }
}

function getStatusText(status: ConnectorStatus, docsIndexed: number): string {
  switch (status) {
    case "connected":
      return docsIndexed > 0
        ? `${docsIndexed.toLocaleString()} docs`
        : "Connected";
    case "indexing":
      return "Indexing...";
    case "error":
      return "Error";
    case "not_connected":
    default:
      return "Not connected";
  }
}

export default function ConnectorCard({
  connectorType,
  config,
  onConfigure,
}: ConnectorCardProps) {
  const sourceMetadata = getSourceMetadata(connectorType);
  const status: ConnectorStatus = config?.status || "not_connected";
  const isConnected = status !== "not_connected";

  return (
    <div className="w-[calc(50%-0.5rem)]">
      <Card variant={isConnected ? "primary" : "secondary"}>
        <button
          onClick={onConfigure}
          className="w-full text-left focus:outline-none"
        >
          <Section
            flexDirection="row"
            justifyContent="between"
            alignItems="center"
            gap={1}
            height="fit"
          >
            <Section
              flexDirection="row"
              alignItems="center"
              gap={0.75}
              width="fit"
              height="fit"
            >
              <SourceIcon sourceType={connectorType} iconSize={24} />
              <Section alignItems="start" gap={0.25} width="fit" height="fit">
                <Text mainUiBody>{sourceMetadata.displayName}</Text>
                <Section
                  flexDirection="row"
                  alignItems="center"
                  gap={0.5}
                  width="fit"
                  height="fit"
                >
                  {getStatusIndicator(status)}
                  <Text secondaryBody text03>
                    {getStatusText(status, config?.docs_indexed || 0)}
                  </Text>
                </Section>
              </Section>
            </Section>

            <SvgSettings className="w-4 h-4 text-text-04" />
          </Section>
        </button>
      </Card>
    </div>
  );
}
