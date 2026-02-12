"use client";

import { useState } from "react";
import Card from "@/refresh-components/cards/Card";
import Popover from "@/refresh-components/Popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";
import { Section, LineItemLayout } from "@/layouts/general-layouts";
import { ValidSources } from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";
import { SvgMoreHorizontal, SvgPlug, SvgSettings, SvgTrash } from "@opal/icons";
import { Button } from "@opal/components";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import IconButton from "@/refresh-components/buttons/IconButton";

export type ConnectorStatus =
  | "not_connected"
  | "connected"
  | "connected_with_errors"
  | "indexing"
  | "error"
  | "deleting";

export interface BuildConnectorConfig {
  cc_pair_id: number;
  connector_id: number;
  credential_id: number;
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
  onDelete: () => void;
}

const STATUS_COLORS: Record<ConnectorStatus, string> = {
  connected: "bg-status-success-05",
  connected_with_errors: "bg-status-warning-05",
  indexing: "bg-status-warning-05 animate-pulse",
  error: "bg-status-error-05",
  deleting: "bg-status-error-05 animate-pulse",
  not_connected: "bg-background-neutral-03",
};

function getStatusText(status: ConnectorStatus, docsIndexed: number): string {
  switch (status) {
    case "connected":
      return docsIndexed > 0
        ? `${docsIndexed.toLocaleString()} docs`
        : "Connected";
    case "connected_with_errors":
      return docsIndexed > 0
        ? `${docsIndexed.toLocaleString()} docs`
        : "Connected, has errors";
    case "indexing":
      return "Syncing...";
    case "error":
      return "Error";
    case "deleting":
      return "Deleting...";
    case "not_connected":
    default:
      return "Not connected";
  }
}

function StatusDescription({
  status,
  docsIndexed,
}: {
  status: ConnectorStatus;
  docsIndexed: number;
}) {
  return (
    <Section
      flexDirection="row"
      alignItems="center"
      gap={0.375}
      width="fit"
      height="fit"
    >
      <div className={cn(STATUS_COLORS[status], "w-2 h-2 rounded-full")} />
      <Text secondaryBody text03>
        {getStatusText(status, docsIndexed)}
      </Text>
    </Section>
  );
}

export default function ConnectorCard({
  connectorType,
  config,
  onConfigure,
  onDelete,
}: ConnectorCardProps) {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const router = useRouter();
  const sourceMetadata = getSourceMetadata(connectorType);
  const status: ConnectorStatus = config?.status || "not_connected";
  const isConnected = status !== "not_connected" && status !== "deleting";
  const isDeleting = status === "deleting";

  // Check if this connector type is always available (doesn't need connection setup)
  const isAlwaysConnected = sourceMetadata.alwaysConnected ?? false;
  const customDescription = sourceMetadata.customDescription;

  const handleCardClick = () => {
    if (isDeleting) {
      return; // No action while deleting
    }
    // Always-connected connectors always go to onConfigure
    if (isAlwaysConnected) {
      onConfigure();
      return;
    }
    if (isConnected) {
      setPopoverOpen(true);
    } else {
      onConfigure();
    }
  };

  // Always-connected connectors show a settings icon
  // Regular connectors show popover menu when connected, plug icon when not
  const rightContent = isDeleting ? null : isAlwaysConnected ? (
    <IconButton icon={SvgSettings} internal />
  ) : isConnected ? (
    <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
      <Popover.Trigger asChild>
        <Button
          icon={SvgMoreHorizontal}
          prominence="tertiary"
          onClick={(e) => {
            e.stopPropagation();
            setPopoverOpen(!popoverOpen);
          }}
        />
      </Popover.Trigger>
      <Popover.Content side="right" align="start" sideOffset={4}>
        <Popover.Menu>
          <LineItem
            key="manage"
            icon={SvgSettings}
            onClick={(e) => {
              e.stopPropagation();
              setPopoverOpen(false);
              router.push(`/admin/connector/${config?.cc_pair_id}`);
            }}
          >
            Manage connector
          </LineItem>
          <LineItem
            key="delete"
            danger
            icon={SvgTrash}
            onClick={(e) => {
              e.stopPropagation();
              setPopoverOpen(false);
              onDelete();
            }}
          >
            Disconnect
          </LineItem>
        </Popover.Menu>
      </Popover.Content>
    </Popover>
  ) : (
    <Button icon={SvgPlug} prominence="tertiary" size="sm" />
  );

  // Always-connected connectors show as "primary" variant
  const cardVariant =
    isAlwaysConnected || isConnected ? "primary" : "secondary";

  // Use custom description if provided, otherwise show status
  const descriptionContent = customDescription ? (
    <Text secondaryBody text03>
      {customDescription}
    </Text>
  ) : (
    <StatusDescription
      status={status}
      docsIndexed={config?.docs_indexed || 0}
    />
  );

  return (
    <div
      className={cn(!isDeleting && "cursor-pointer")}
      onClick={handleCardClick}
    >
      <Card variant={cardVariant}>
        <LineItemLayout
          icon={sourceMetadata.icon}
          title={sourceMetadata.displayName}
          description={descriptionContent}
          rightChildren={rightContent}
          center
        />
      </Card>
    </div>
  );
}
