"use client";

import { ThreeDotsLoader } from "@/components/Loading";
import { PageSelector } from "@/components/PageSelector";
import { InfoIcon } from "@/components/icons/icons";

import { useConnectorCredentialIndexingStatus } from "@/lib/hooks";
import { ConnectorIndexingStatus, DocumentSet } from "@/lib/types";
import { useState, useEffect } from "react";
import { useDocumentSets } from "./hooks";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
import { deleteDocumentSet } from "./lib";
import { AdminPageTitle } from "@/components/admin/Title";
import { DeleteButton } from "@/components/DeleteButton";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Bookmark, CircleCheckBig, Clock, TriangleAlert } from "lucide-react";
import { CustomTooltip } from "@/components/CustomTooltip";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { useToast } from "@/hooks/use-toast";
import { FiEdit2 } from "react-icons/fi";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { TableHeaderCell } from "@tremor/react";

const numToDisplay = 50;

const EditRow = ({
  documentSet,
  isEditable,
}: {
  documentSet: DocumentSet;
  isEditable: boolean;
}) => {
  const router = useRouter();

  const [isSyncingTooltipOpen, setIsSyncingTooltipOpen] = useState(false);

  if (!isEditable) {
    return (
      <div className="text-emphasis font-medium my-auto p-1">
        {documentSet.name}
      </div>
    );
  }

  return (
    <div className="relative flex">
      {isSyncingTooltipOpen && (
        <div className="flex flex-nowrap absolute w-64 top-0 left-0 mt-8 border border-border bg-background px-3 py-2 rounded shadow-lg break-words z-40">
          <InfoIcon className="mt-1 flex flex-shrink-0 mr-2" /> Cannot update
          while syncing! Wait for the sync to finish, then try again.
        </div>
      )}
      <div
        className={`
          text-emphasis font-medium my-auto p-1 hover:bg-hover-light flex items-center select-none
          ${documentSet.is_up_to_date ? "cursor-pointer" : "cursor-default"}
        `}
        style={{ wordBreak: "normal", overflowWrap: "break-word" }}
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
        <FiEdit2 className="mr-2 flex-shrink-0" />
        <span className="font-medium">{documentSet.name}</span>
      </div>
    </div>
  );
};

interface DocumentFeedbackTableProps {
  documentSets: DocumentSet[];
  ccPairs: ConnectorIndexingStatus<any, any>[];
  refresh: () => void;
  refreshEditable: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  editableDocumentSets: DocumentSet[];
}

const DocumentSetTable = ({
  documentSets,
  editableDocumentSets,
  refresh,
  refreshEditable,
  setPopup,
}: DocumentFeedbackTableProps) => {
  const [page, setPage] = useState(1);
  const { toast } = useToast();

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

  const sortedDocumentSets = [
    ...editableDocumentSets,
    ...documentSets.filter(
      (ds) => !editableDocumentSets.some((eds) => eds.id === ds.id)
    ),
  ];

  return (
    <div>
      <h3 className="pb-4">Existing Document Sets</h3>
      <Card>
        <CardContent className="p-0">
          <Table className="overflow-visible mt-2">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Name</TableHeaderCell>
                <TableHeaderCell>Connectors</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
                <TableHeaderCell>Public</TableHeaderCell>
                <TableHeaderCell>Delete</TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedDocumentSets
                .slice((page - 1) * numToDisplay, page * numToDisplay)
                .map((documentSet) => {
                  const isEditable = editableDocumentSets.some(
                    (eds) => eds.id === documentSet.id
                  );
                  return (
                    <TableRow key={documentSet.id}>
                      <TableCell className="whitespace-normal break-all">
                        <div className="flex gap-x-1 text-emphasis">
                          <EditRow
                            documentSet={documentSet}
                            isEditable={isEditable}
                          />
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
                          <Badge
                            variant="success"
                            className="whitespace-nowrap"
                          >
                            <CircleCheckBig size={14} /> Up to Date
                          </Badge>
                        ) : documentSet.cc_pair_descriptors.length > 0 ? (
                          <Badge variant="outline">
                            <Clock size={14} /> Syncing
                          </Badge>
                        ) : (
                          <Badge variant="destructive">
                            <TriangleAlert size={14} /> Deleting
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {documentSet.is_public ? (
                          <Badge>Global</Badge>
                        ) : (
                          <Badge variant="secondary">Private</Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {isEditable ? (
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
                              refreshEditable();
                            }}
                          />
                        ) : (
                          "-"
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <div className="flex pt-6">
        <div className="mx-auto">
          <PageSelector
            totalPages={Math.ceil(sortedDocumentSets.length / numToDisplay)}
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
    data: editableDocumentSets,
    isLoading: isEditableDocumentSetsLoading,
    error: editableDocumentSetsError,
    refreshDocumentSets: refreshEditableDocumentSets,
  } = useDocumentSets(true);

  const {
    data: ccPairs,
    isLoading: isCCPairsLoading,
    error: ccPairsError,
  } = useConnectorCredentialIndexingStatus();

  if (
    isDocumentSetsLoading ||
    isCCPairsLoading ||
    isEditableDocumentSetsLoading
  ) {
    return <ThreeDotsLoader />;
  }

  if (documentSetsError || !documentSets) {
    return <div>Error: {documentSetsError}</div>;
  }

  if (editableDocumentSetsError || !editableDocumentSets) {
    return <div>Error: {editableDocumentSetsError}</div>;
  }

  if (ccPairsError || !ccPairs) {
    return <div>Error: {ccPairsError}</div>;
  }

  return (
    <div>
      <p className="pb-6">
        <b>Document Sets</b> allow you to group logically connected documents
        into a single bundle. These can then be used as filter when performing
        searches in the web UI to limit the amount of information the bot
        searches over when answering in a specific channel or with a certain
        command.
      </p>

      <div className="flex pb-6">
        <Link href="/admin/documents/sets/new">
          <Button className="my-auto">New Document Set</Button>
        </Link>
      </div>

      {documentSets.length > 0 && (
        <>
          <DocumentSetTable
            documentSets={documentSets}
            editableDocumentSets={editableDocumentSets}
            ccPairs={ccPairs}
            refresh={refreshDocumentSets}
            refreshEditable={refreshEditableDocumentSets}
            setPopup={setPopup}
          />
        </>
      )}
    </div>
  );
};

const Page = () => {
  return (
    <div className="h-full w-full overflow-y-auto">
      <div className="container">
        <AdminPageTitle icon={<Bookmark size={32} />} title="Document Sets" />

        <Main />
      </div>
    </div>
  );
};

export default Page;
