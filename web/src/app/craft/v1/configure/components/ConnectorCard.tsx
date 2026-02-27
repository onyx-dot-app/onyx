"use client";

import { useState } from "react";
import Card from "@/refresh-components/cards/Card";
import Popover from "@/refresh-components/Popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import { ContentAction } from "@opal/layouts";
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

  const descriptionText =
    customDescription ?? getStatusText(status, config?.docs_indexed || 0);

  return (
    <div
      className={cn(!isDeleting && "cursor-pointer")}
      onClick={handleCardClick}
    >
      <Card variant={cardVariant}>
        <ContentAction
          icon={sourceMetadata.icon}
          title={sourceMetadata.displayName}
          description={descriptionText}
          sizePreset="main-content"
          variant="section"
          rightChildren={rightContent}
        />
      </Card>
    </div>
  );
}
