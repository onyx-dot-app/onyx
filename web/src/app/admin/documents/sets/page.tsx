"use client";

import { ThreeDotsLoader } from "@/components/Loading";
import { PageSelector } from "@/components/PageSelector";
import { BookmarkIcon, InfoIcon } from "@/components/icons/icons";
import {
  Table,
  TableHead,
  TableRow,
  TableHeaderCell,
  TableBody,
  TableCell,
  Title,
  Divider,
  Badge,
} from "@tremor/react";
import { useConnectorCredentialIndexingStatus } from "@/lib/hooks";
import { ConnectorIndexingStatus, DocumentSet } from "@/lib/types";
import { useState } from "react";
import { useDocumentSets } from "./hooks";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
import { deleteDocumentSet } from "./lib";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { AdminPageTitle } from "@/components/admin/Title";
import { Button, Text } from "@tremor/react";
import {
  FiAlertTriangle,
  FiCheckCircle,
  FiClock,
  FiEdit2,
} from "react-icons/fi";
import { DeleteButton } from "@/components/DeleteButton";
import Link from "next/link";
import { useRouter } from "next/navigation";

const numToDisplay = 50;

const EditRow = ({ documentSet }: { documentSet: DocumentSet }) => {
  const router = useRouter();

  const [isSyncingTooltipOpen, setIsSyncingTooltipOpen] = useState(false);
  return (
    <div className="relative flex">
      {isSyncingTooltipOpen && (
        <div className="flex flex-nowrap absolute w-64 top-0 left-0 mt-8 border border-border bg-background px-3 py-2 rounded shadow-lg break-words z-40">
          <InfoIcon className="mt-1 flex flex-shrink-0 mr-2" /> Cannot update
          while syncing! Wait for the sync to finish, then try again.
        </div>
      )}
      <div
        className={
          "text-emphasis font-medium my-auto p-1 hover:bg-hover-light flex cursor-pointer select-none" +
          (documentSet.is_up_to_date ? " cursor-pointer" : " cursor-default")
        }
        onClick={() => {
          if (documentSet.is_up_to_date) {
            router.push(`/admin/documents/sets/${documentSet.id}`);
          }
        }}
        onMouseEnter={() => {
          if (!documentSet.is_up_to_date) {
            setIsSyncingTooltipOpen(true);
          }
        }}
        onMouseLeave={() => {
          if (!documentSet.is_up_to_date) {
            setIsSyncingTooltipOpen(false);
          }
        }}
      >
        <FiEdit2 className="text-emphasis mr-1 my-auto" />
        {documentSet.name}
      </div>
    </div>
  );
};

interface DocumentFeedbackTableProps {
  documentSets: DocumentSet[];
  ccPairs: ConnectorIndexingStatus<any, any>[];
  refresh: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
}

const DocumentSetTable = ({
  documentSets,
  refresh,
  setPopup,
}: DocumentFeedbackTableProps) => {
  const [page, setPage] = useState(1);

  // sort by name for consistent ordering
  documentSets.sort((a, b) => {
    if (a.name < b.name) {
      return -1;
    } else if (a.name > b.name) {
      return 1;
    } else {
      return 0;
    }
  });

  return (
    <div>
      <Title>Existing Document Sets</Title>
      <Table className="overflow-visible mt-2">
        <TableHead>
          <TableRow>
            <TableHeaderCell>Name</TableHeaderCell>
            <TableHeaderCell>Connectors</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell>Delete</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {documentSets
            .slice((page - 1) * numToDisplay, page * numToDisplay)
            .map((documentSet) => {
              return (
                <TableRow key={documentSet.id}>
                  <TableCell className="whitespace-normal break-all">
                    <div className="flex gap-x-1 text-emphasis">
                      <EditRow documentSet={documentSet} />
                    </div>
                  </TableCell>
                  <TableCell>
                    <div>
                      {documentSet.cc_pair_descriptors.map(
                        (ccPairDescriptor, ind) => {
                          return (
                            <div
                              className={
                                ind !==
                                documentSet.cc_pair_descriptors.length - 1
                                  ? "mb-3"
                                  : ""
                              }
                              key={ccPairDescriptor.id}
                            >
                              <ConnectorTitle
                                connector={ccPairDescriptor.connector}
                                ccPairName={ccPairDescriptor.name}
                                ccPairId={ccPairDescriptor.id}
                                showMetadata={false}
                              />
                            </div>
                          );
                        }
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    {documentSet.is_up_to_date ? (
                      <Badge size="md" color="green" icon={FiCheckCircle}>
                        Up to Date
                      </Badge>
                    ) : documentSet.cc_pair_descriptors.length > 0 ? (
                      <Badge size="md" color="amber" icon={FiClock}>
                        Syncing
                      </Badge>
                    ) : (
                      <Badge size="md" color="red" icon={FiAlertTriangle}>
                        Deleting
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    <DeleteButton
                      onClick={async () => {
                        const response = await deleteDocumentSet(
                          documentSet.id
                        );
                        if (response.ok) {
                          setPopup({
                            message: `Document set "${documentSet.name}" scheduled for deletion`,
                            type: "success",
                          });
                        } else {
                          const errorMsg = (await response.json()).detail;
                          setPopup({
                            message: `Failed to schedule document set for deletion - ${errorMsg}`,
                            type: "error",
                          });
                        }
                        refresh();
                      }}
                    />
                  </TableCell>
                </TableRow>
              );
            })}
        </TableBody>
      </Table>

      <div className="mt-3 flex">
        <div className="mx-auto">
          <PageSelector
            totalPages={Math.ceil(documentSets.length / numToDisplay)}
            currentPage={page}
            onPageChange={(newPage) => setPage(newPage)}
          />
        </div>
      </div>
    </div>
  );
};

const Main = () => {
  const { popup, setPopup } = usePopup();
  const {
    data: documentSets,
    isLoading: isDocumentSetsLoading,
    error: documentSetsError,
    refreshDocumentSets,
  } = useDocumentSets();

  const {
    data: ccPairs,
    isLoading: isCCPairsLoading,
    error: ccPairsError,
  } = useConnectorCredentialIndexingStatus();

  if (isDocumentSetsLoading || isCCPairsLoading) {
    return <ThreeDotsLoader />;
  }

  if (documentSetsError || !documentSets) {
    return <div>Error: {documentSetsError}</div>;
  }

  if (ccPairsError || !ccPairs) {
    return <div>Error: {ccPairsError}</div>;
  }

  return (
    <div className="mb-8">
      {popup}
      <Text className="mb-3">
        <b>Document Sets</b> allow you to group logically connected documents
        into a single bundle. These can then be used as filter when performing
        searches in the web UI or attached to slack bots to limit the amount of
        information the bot searches over when answering in a specific channel
        or with a certain command.
      </Text>

      <div className="mb-3"></div>

      <div className="flex mb-6">
        <Link href="/admin/documents/sets/new">
          <Button size="xs" color="green" className="ml-2 my-auto">
            New Document Set
          </Button>
        </Link>
      </div>

      {documentSets.length > 0 && (
        <>
          <Divider />
          <DocumentSetTable
            documentSets={documentSets}
            ccPairs={ccPairs}
            refresh={refreshDocumentSets}
            setPopup={setPopup}
          />
        </>
      )}
    </div>
  );
};

const Page = () => {
  return (
    <div className="container mx-auto">
      <AdminPageTitle icon={<BookmarkIcon size={32} />} title="Document Sets" />

      <Main />
    </div>
  );
};

export default Page;
