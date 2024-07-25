import { DeletionAttemptSnapshot, ValidStatuses } from "@/lib/types";
import { usePopup } from "@/components/admin/connectors/Popup";
import { updateConnector } from "@/lib/connector";
import { AttachCredentialButtonForTable } from "@/components/admin/connectors/buttons/AttachCredentialButtonForTable";
import { scheduleDeletionJobForConnector } from "@/lib/documentDeletion";
import { ConnectorsTableProps } from "./ConnectorsTable";
import {
  Table,
  TableHead,
  TableRow,
  TableHeaderCell,
  TableBody,
  TableCell,
} from "@tremor/react";
import { DeleteButton } from "@/components/DeleteButton";

const SingleUseConnectorStatus = ({
  indexingStatus,
  deletionAttempt,
}: {
  indexingStatus: ValidStatuses | null;
  deletionAttempt: DeletionAttemptSnapshot | null;
}) => {
  if (
    deletionAttempt &&
    (deletionAttempt.status === "PENDING" ||
      deletionAttempt.status === "STARTED")
  ) {
    return <div className="text-error">Deleting...</div>;
  }

  if (!indexingStatus || indexingStatus === "not_started") {
    return <div>Not Started</div>;
  }

  if (indexingStatus === "in_progress") {
    return <div>In Progress</div>;
  }

  if (indexingStatus === "success") {
    return <div className="text-success">Success!</div>;
  }

  return <div className="text-error">Failed</div>;
};

export function SingleUseConnectorsTable<
  ConnectorConfigType,
  ConnectorCredentialType,
>({
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
                  <TableCell className="max-w-sm" key={key}>
                    <div className="break-words whitespace-normal">
                      {getValue(connectorIndexingStatus)}
                    </div>
                  </TableCell>
                ))}
                <TableCell>
                  <SingleUseConnectorStatus
                    indexingStatus={connectorIndexingStatus.last_status}
                    deletionAttempt={connectorIndexingStatus.deletion_attempt}
                  />
                </TableCell>
                {connectorIncludesCredential && (
                  <TableCell>{credentialDisplay}</TableCell>
                )}
                <TableCell>
                  <div
                    className="cursor-pointer mx-auto flex"
                    onClick={async () => {
                      // for one-time, just disable the connector at deletion time
                      // this is required before deletion can happen
                      await updateConnector({
                        ...connector,
                        disabled: !connector.disabled,
                      });

                      const deletionScheduleError =
                        await scheduleDeletionJobForConnector(
                          connector.id,
                          connectorIndexingStatus.credential.id
                        );
                      if (deletionScheduleError) {
                        setPopup({
                          message:
                            "Failed to schedule deletion of connector - " +
                            deletionScheduleError,
                          type: "error",
                        });
                      } else {
                        setPopup({
                          message: "Scheduled deletion of connector!",
                          type: "success",
                        });
                      }
                      setTimeout(() => {
                        setPopup(null);
                      }, 4000);
                      onUpdate();
                    }}
                  >
                    <DeleteButton />
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
