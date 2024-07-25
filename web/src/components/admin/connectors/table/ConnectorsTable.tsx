import { ConnectorIndexingStatus, Credential } from "@/lib/types";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { useState } from "react";
import { LinkBreakIcon, LinkIcon } from "@/components/icons/icons";
import { disableConnector } from "@/lib/connector";
import { AttachCredentialButtonForTable } from "@/components/admin/connectors/buttons/AttachCredentialButtonForTable";
import { DeleteColumn } from "./DeleteColumn";
import {
  Table,
  TableHead,
  TableRow,
  TableHeaderCell,
  TableBody,
  TableCell,
} from "@tremor/react";
import { FiCheck, FiXCircle } from "react-icons/fi";

interface StatusRowProps<ConnectorConfigType, ConnectorCredentialType> {
  connectorIndexingStatus: ConnectorIndexingStatus<
    ConnectorConfigType,
    ConnectorCredentialType
  >;
  hasCredentialsIssue: boolean;
  setPopup: (popupSpec: PopupSpec | null) => void;
  onUpdate: () => void;
}

export function StatusRow<ConnectorConfigType, ConnectorCredentialType>({
  connectorIndexingStatus,
  hasCredentialsIssue,
  setPopup,
  onUpdate,
}: StatusRowProps<ConnectorConfigType, ConnectorCredentialType>) {
  const [statusHovered, setStatusHovered] = useState<boolean>(false);
  const connector = connectorIndexingStatus.connector;

  let shouldDisplayDisabledToggle = !hasCredentialsIssue;
  let statusDisplay;
  switch (connectorIndexingStatus.last_status) {
    case "failed":
      statusDisplay = <div className="text-error">Failed</div>;
      break;
    default:
      statusDisplay = <div className="text-success flex">Enabled!</div>;
  }
  if (connector.disabled) {
    const deletionAttempt = connectorIndexingStatus.deletion_attempt;
    if (!deletionAttempt || deletionAttempt.status === "FAILURE") {
      statusDisplay = <div className="text-error">Paused</div>;
    } else {
      statusDisplay = <div className="text-error">Deleting...</div>;
      shouldDisplayDisabledToggle = false;
    }
  }

  return (
    <div className="flex">
      {statusDisplay}
      {shouldDisplayDisabledToggle && (
        <div
          className="cursor-pointer ml-1 my-auto relative"
          onMouseEnter={() => setStatusHovered(true)}
          onMouseLeave={() => setStatusHovered(false)}
          onClick={() => disableConnector(connector, setPopup, onUpdate)}
        >
          {statusHovered && (
            <div className="flex flex-nowrap absolute top-0 left-0 ml-8 bg-background border border-border px-3 py-2 rounded shadow-lg">
              {connector.disabled ? "Enable!" : "Pause!"}
            </div>
          )}
          {connector.disabled ? (
            <LinkIcon className="my-auto flex flex-shrink-0 text-error" />
          ) : (
            <LinkBreakIcon
              className={`my-auto flex flex-shrink-0 ${
                connectorIndexingStatus.last_status === "failed"
                  ? "text-error"
                  : "text-success"
              }`}
            />
          )}
        </div>
      )}
    </div>
  );
}

export interface ColumnSpecification<
  ConnectorConfigType,
  ConnectorCredentialType,
> {
  header: string;
  key: string;
  getValue: (
    ccPairStatus: ConnectorIndexingStatus<
      ConnectorConfigType,
      ConnectorCredentialType
    >
  ) => JSX.Element | string | undefined;
}

export interface ConnectorsTableProps<
  ConnectorConfigType,
  ConnectorCredentialType,
> {
  connectorIndexingStatuses: ConnectorIndexingStatus<
    ConnectorConfigType,
    ConnectorCredentialType
  >[];
  liveCredential?: Credential<ConnectorCredentialType> | null;
  getCredential?: (
    credential: Credential<ConnectorCredentialType>
  ) => JSX.Element | string;
  onUpdate: () => void;
  onCredentialLink?: (connectorId: number) => void;
  specialColumns?: ColumnSpecification<
    ConnectorConfigType,
    ConnectorCredentialType
  >[];
  includeName?: boolean;
}

export function ConnectorsTable<ConnectorConfigType, ConnectorCredentialType>({
  connectorIndexingStatuses,
  liveCredential,
  getCredential,
  specialColumns,
  onUpdate,
  onCredentialLink,
  includeName = false,
}: ConnectorsTableProps<ConnectorConfigType, ConnectorCredentialType>) {
  const { popup, setPopup } = usePopup();

  const connectorIncludesCredential =
    getCredential !== undefined && onCredentialLink !== undefined;

  const columns = [
    ...(includeName ? [{ header: "Name", key: "name" }] : []),
    ...(specialColumns ?? []),
    {
      header: "Status",
      key: "status",
    },
    {
      header: "Is Public",
      key: "is_public",
    },
  ];
  if (connectorIncludesCredential) {
    columns.push({
      header: "Credential",
      key: "credential",
    });
  }
  columns.push({
    header: "Remove",
    key: "remove",
  });

  return (
    <div>
      {popup}

      <Table className="overflow-visible">
        <TableHead>
          <TableRow>
            {includeName && <TableHeaderCell>Name</TableHeaderCell>}
            {specialColumns?.map(({ header }) => (
              <TableHeaderCell key={header}>{header}</TableHeaderCell>
            ))}
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell>Is Public</TableHeaderCell>
            {connectorIncludesCredential && (
              <TableHeaderCell>Credential</TableHeaderCell>
            )}
            <TableHeaderCell>Remove</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {connectorIndexingStatuses.map((connectorIndexingStatus) => {
            const connector = connectorIndexingStatus.connector;
            // const credential = connectorIndexingStatus.credential;
            const hasValidCredentials =
              liveCredential &&
              connector.credential_ids.includes(liveCredential.id);
            const credentialDisplay = connectorIncludesCredential ? (
              hasValidCredentials ? (
                <div className="max-w-sm truncate">
                  {getCredential(liveCredential)}
                </div>
              ) : liveCredential ? (
                <AttachCredentialButtonForTable
                  onClick={() => onCredentialLink(connector.id)}
                />
              ) : (
                <p className="text-red-700">N/A</p>
              )
            ) : (
              "-"
            );
            return (
              <TableRow key={connectorIndexingStatus.cc_pair_id}>
                {includeName && (
                  <TableCell className="whitespace-normal break-all">
                    <p className="text font-medium">
                      {connectorIndexingStatus.name}
                    </p>
                  </TableCell>
                )}
                {specialColumns?.map(({ key, getValue }) => (
                  <TableCell key={key}>
                    {getValue(connectorIndexingStatus)}
                  </TableCell>
                ))}
                <TableCell>
                  <StatusRow
                    connectorIndexingStatus={connectorIndexingStatus}
                    hasCredentialsIssue={
                      !hasValidCredentials && connectorIncludesCredential
                    }
                    setPopup={setPopup}
                    onUpdate={onUpdate}
                  />
                </TableCell>
                <TableCell>
                  {connectorIndexingStatus.public_doc ? (
                    <FiCheck className="my-auto text-success" size="18" />
                  ) : (
                    <FiXCircle className="my-auto text-error" />
                  )}
                </TableCell>
                {connectorIncludesCredential && (
                  <TableCell>{credentialDisplay}</TableCell>
                )}
                <TableCell>
                  <DeleteColumn
                    connectorIndexingStatus={connectorIndexingStatus}
                    setPopup={setPopup}
                    onUpdate={onUpdate}
                  />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
