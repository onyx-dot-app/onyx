import { buildCCPairInfoUrl } from "@/app/admin/connector/[ccPairId]/lib";
import { PageSelector } from "@/components/PageSelector";
import { IndexAttemptStatus } from "@/components/Status";
import { deleteCCPair } from "@/lib/documentDeletion";
import { FailedConnectorIndexingStatus } from "@/lib/types";
import Button from "@/refresh-components/buttons/Button";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import Text from "@/components/ui/text";
import Link from "next/link";
import { useState } from "react";
import { FiLink, FiMaximize2, FiTrash } from "react-icons/fi";
import { mutate } from "swr";
import { PopupSpec } from "../admin/connectors/Popup";
import { SvgTrash } from "@opal/icons";
export function FailedReIndexAttempts({
  failedIndexingStatuses,
  setPopup,
}: {
  failedIndexingStatuses: FailedConnectorIndexingStatus[];
  setPopup: (popupSpec: PopupSpec | null) => void;
}) {
  const numToDisplay = 10;
  const [page, setPage] = useState(1);
  const [pendingConnectorDeletion, setPendingConnectorDeletion] = useState<{
    connectorId: number;
    credentialId: number;
    ccPairId: number;
    name: string;
  } | null>(null);

  const shouldConfirmConnectorDeletion = true;

  const anyDeletable = failedIndexingStatuses.some(
    (status) => status.is_deletable
  );

  return (
    <div className="mt-6 mb-8 p-4 border border-status-error-02 bg-status-error-00 rounded-lg">
      {pendingConnectorDeletion && (
        <ConfirmEntityModal
          danger
          entityType="connector"
          entityName={pendingConnectorDeletion.name}
          additionalDetails="Deleting this connector schedules a deletion job that removes its indexed documents and deletes it for every user."
          onClose={() => setPendingConnectorDeletion(null)}
          onSubmit={async () => {
            try {
              await deleteCCPair(
                pendingConnectorDeletion.connectorId,
                pendingConnectorDeletion.credentialId,
                setPopup,
                () =>
                  mutate(buildCCPairInfoUrl(pendingConnectorDeletion.ccPairId))
              );
            } catch (error) {
              console.error("Error deleting connector:", error);
              setPopup({
                message: "Failed to delete connector. Please try again.",
                type: "error",
              });
            } finally {
              setPendingConnectorDeletion(null);
            }
          }}
        />
      )}

      <Text className="text-status-error-05 font-semibold mb-2">
        Failed Re-indexing Attempts
      </Text>
      <Text className="text-status-error-05 mb-4">
        The table below shows only the failed re-indexing attempts for existing
        connectors. These failures require immediate attention. Once all
        connectors have been re-indexed successfully, the new model will be used
        for all search queries.
      </Text>

      <div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-1/8 sm:w-1/6">Connector Name</TableHead>
              <TableHead className="w-1/8 sm:w-1/6">Status</TableHead>
              <TableHead className="w-4/8 sm:w-2/6">Error Message</TableHead>
              <TableHead className="w-1/8 sm:w-1/6">Visit Connector</TableHead>
              {anyDeletable && (
                <TableHead className="w-1/8 sm:w-2/6">
                  Delete Connector
                </TableHead>
              )}
            </TableRow>
          </TableHeader>
          <TableBody>
            {failedIndexingStatuses
              .slice(numToDisplay * (page - 1), numToDisplay * page)
              .map((reindexingProgress) => {
                return (
                  <TableRow key={reindexingProgress.name}>
                    <TableCell>
                      <Link
                        href={`/admin/connector/${reindexingProgress.cc_pair_id}`}
                        className="text-link cursor-pointer flex"
                      >
                        <FiMaximize2 className="my-auto mr-1" />
                        {reindexingProgress.name}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <IndexAttemptStatus status="failed" />
                    </TableCell>

                    <TableCell>
                      <div>
                        <Text className="flex flex-wrap whitespace-normal">
                          {reindexingProgress.error_msg || "-"}
                        </Text>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Link
                        href={`/admin/connector/${reindexingProgress.cc_pair_id}`}
                        className="ctext-link cursor-pointer flex"
                      >
                        <FiLink className="my-auto mr-1" />
                        Visit Connector
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Button
                        danger
                        onClick={async () => {
                          if (shouldConfirmConnectorDeletion) {
                            setPendingConnectorDeletion({
                              connectorId: reindexingProgress.connector_id,
                              credentialId: reindexingProgress.credential_id,
                              ccPairId: reindexingProgress.cc_pair_id,
                              name: reindexingProgress.name ?? "this connector",
                            });
                            return;
                          }

                          try {
                            await deleteCCPair(
                              reindexingProgress.connector_id,
                              reindexingProgress.credential_id,
                              setPopup,
                              () =>
                                mutate(
                                  buildCCPairInfoUrl(
                                    reindexingProgress.cc_pair_id
                                  )
                                )
                            );
                          } catch (error) {
                            console.error("Error deleting connector:", error);
                            setPopup({
                              message:
                                "Failed to delete connector. Please try again.",
                              type: "error",
                            });
                          }
                        }}
                        leftIcon={SvgTrash}
                        disabled={!reindexingProgress.is_deletable}
                      >
                        Delete
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
          </TableBody>
        </Table>

        <div className="mt-3 flex">
          <div className="mx-auto">
            <PageSelector
              totalPages={Math.ceil(
                failedIndexingStatuses.length / numToDisplay
              )}
              currentPage={page}
              onPageChange={(newPage) => setPage(newPage)}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
