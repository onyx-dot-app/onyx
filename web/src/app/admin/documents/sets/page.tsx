"use client";

import { ThreeDotsLoader } from "@/components/Loading";
import { PageSelector } from "@/components/PageSelector";
import { BookmarkIcon, InfoIcon } from "@/components/icons/icons";
import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
} from "@/components/ui/table";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { Separator } from "@/components/ui/separator";
import { DocumentSetSummary } from "@/lib/types";
import { useState } from "react";
import { useDocumentSets } from "./hooks";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
import { deleteDocumentSet } from "./lib";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { AdminPageTitle } from "@/components/admin/Title";
import {
  FiAlertTriangle,
  FiCheckCircle,
  FiClock,
  FiEdit2,
  FiLock,
  FiUnlock,
} from "react-icons/fi";
import { DeleteButton } from "@/components/DeleteButton";
import { useRouter } from "next/navigation";
import { TableHeader } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import { SourceIcon } from "@/components/SourceIcon";
import Link from "next/link";

const numToDisplay = 50;

// Component to display federated connectors with consistent styling
const FederatedConnectorTitle = ({
  federatedConnector,
  showMetadata = true,
  isLink = true,
}: {
  federatedConnector: any;
  showMetadata?: boolean;
  isLink?: boolean;
}) => {
  const sourceType = federatedConnector.source.replace(/^federated_/, "");

  const mainSectionClassName = "text-blue-500 dark:text-blue-100 flex w-fit";
  const mainDisplay = (
    <>
      <SourceIcon sourceType={sourceType as any} iconSize={16} />
      <div className="ml-1 my-auto text-xs font-medium truncate">
        {federatedConnector.name}
      </div>
      <Badge variant="outline" className="text-xs ml-2">
        Federated
      </Badge>
    </>
  );

  return (
    <div className="my-auto max-w-full">
      {isLink ? (
        <Link
          className={mainSectionClassName}
          href={`/admin/federated/${federatedConnector.id}`}
        >
          {mainDisplay}
        </Link>
      ) : (
        <div className={mainSectionClassName}>{mainDisplay}</div>
      )}
      {showMetadata && Object.keys(federatedConnector.entities).length > 0 && (
        <div className="text-[10px] mt-0.5 text-gray-600 dark:text-gray-400">
          {Object.entries(federatedConnector.entities)
            .filter(
              ([_, value]) =>
                value &&
                (Array.isArray(value) ? value.length > 0 : String(value).trim())
            )
            .map(([key, value]) => (
              <div key={key} className="truncate">
                <i>{key}:</i>{" "}
                {Array.isArray(value) ? value.join(", ") : String(value)}
              </div>
            ))}
        </div>
      )}
    </div>
  );
};

const EditRow = ({
  documentSet,
  isEditable,
}: {
  documentSet: DocumentSetSummary;
  isEditable: boolean;
}) => {
  const router = useRouter();

  if (!isEditable) {
    return (
      <div className="text-text-darker font-medium my-auto p-1">
        {documentSet.name}
      </div>
    );
  }

  return (
    <div className="relative flex">
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div
              className={`
              text-text-darker font-medium my-auto p-1 hover:bg-accent-background flex items-center select-none
              ${documentSet.is_up_to_date ? "cursor-pointer" : "cursor-default"}
            `}
              style={{ wordBreak: "normal", overflowWrap: "break-word" }}
              onClick={() => {
                if (documentSet.is_up_to_date) {
                  router.push(`/admin/documents/sets/${documentSet.id}`);
                }
              }}
            >
              <FiEdit2 className="mr-2 flex-shrink-0" />
              <span className="font-medium">{documentSet.name}</span>
            </div>
          </TooltipTrigger>
          {!documentSet.is_up_to_date && (
            <TooltipContent width="max-w-sm">
              <div className="flex break-words break-keep whitespace-pre-wrap items-start">
                <InfoIcon className="mr-2 mt-0.5" />
                Cannot update while syncing! Wait for the sync to finish, then
                try again.
              </div>
            </TooltipContent>
          )}
        </Tooltip>
      </TooltipProvider>
    </div>
  );
};

interface DocumentFeedbackTableProps {
  documentSets: DocumentSetSummary[];
  refresh: () => void;
  refreshEditable: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  editableDocumentSets: DocumentSetSummary[];
}

const DocumentSetTable = ({
  documentSets,
  editableDocumentSets,
  refresh,
  refreshEditable,
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

  const sortedDocumentSets = [
    ...editableDocumentSets,
    ...documentSets.filter(
      (ds) => !editableDocumentSets.some((eds) => eds.id === ds.id)
    ),
  ];

  return (
    <div>
      <Title>Existing Document Sets</Title>
      <Table className="overflow-visible mt-2">
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Connectors</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Public</TableHead>
            <TableHead>Delete</TableHead>
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
                      {/* Regular Connectors */}
                      {documentSet.cc_pair_summaries.map(
                        (ccPairSummary, ind) => {
                          return (
                            <div
                              className={
                                ind !== documentSet.cc_pair_summaries.length - 1
                                  ? "mb-3"
                                  : ""
                              }
                              key={ccPairSummary.id}
                            >
                              <div className="text-blue-500 dark:text-blue-100 flex w-fit">
                                <SourceIcon
                                  sourceType={ccPairSummary.source}
                                  iconSize={16}
                                />
                                <div className="ml-1 my-auto text-xs font-medium truncate">
                                  {ccPairSummary.name || "Unnamed"}
                                </div>
                              </div>
                            </div>
                          );
                        }
                      )}

                      {/* Federated Connectors */}
                      {documentSet.federated_connector_summaries &&
                        documentSet.federated_connector_summaries.length >
                          0 && (
                          <>
                            {documentSet.cc_pair_summaries.length > 0 && (
                              <div className="mb-3" />
                            )}
                            {documentSet.federated_connector_summaries.map(
                              (federatedConnector, ind) => {
                                return (
                                  <div
                                    className={
                                      ind !==
                                      documentSet.federated_connector_summaries
                                        .length -
                                        1
                                        ? "mb-3"
                                        : ""
                                    }
                                    key={`federated-${federatedConnector.id}`}
                                  >
                                    <FederatedConnectorTitle
                                      federatedConnector={federatedConnector}
                                      showMetadata={true}
                                    />
                                  </div>
                                );
                              }
                            )}
                          </>
                        )}
                    </div>
                  </TableCell>
                  <TableCell>
                    {documentSet.is_up_to_date ? (
                      <Badge variant="success" icon={FiCheckCircle}>
                        Up to Date
                      </Badge>
                    ) : documentSet.cc_pair_summaries.length > 0 ||
                      (documentSet.federated_connector_summaries &&
                        documentSet.federated_connector_summaries.length >
                          0) ? (
                      <Badge variant="in_progress" icon={FiClock}>
                        Syncing
                      </Badge>
                    ) : (
                      <Badge variant="destructive" icon={FiAlertTriangle}>
                        Deleting
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {documentSet.is_public ? (
                      <Badge
                        variant={isEditable ? "success" : "default"}
                        icon={FiUnlock}
                      >
                        Public
                      </Badge>
                    ) : (
                      <Badge
                        variant={isEditable ? "private" : "default"}
                        icon={FiLock}
                      >
                        Private
                      </Badge>
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

      <div className="mt-3 flex">
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

  if (isDocumentSetsLoading || isEditableDocumentSetsLoading) {
    return (
      <div className="flex justify-center items-center min-h-[400px]">
        <ThreeDotsLoader />
      </div>
    );
  }

  if (documentSetsError || !documentSets) {
    return <div>Error: {documentSetsError}</div>;
  }

  if (editableDocumentSetsError || !editableDocumentSets) {
    return <div>Error: {editableDocumentSetsError}</div>;
  }

  return (
    <div className="mb-8">
      {popup}
      <Text className="mb-3">
        <b>Document Sets</b> allow you to group logically connected documents
        into a single bundle. These can then be used as a filter when performing
        searches to control the scope of information Onyx searches over.
      </Text>

      <div className="mb-3"></div>

      <div className="flex mb-6">
        <CreateButton href="/admin/documents/sets/new">
          New Document Set
        </CreateButton>
      </div>

      {documentSets.length > 0 && (
        <>
          <Separator />
          <DocumentSetTable
            documentSets={documentSets}
            editableDocumentSets={editableDocumentSets}
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
    <div className="container mx-auto">
      <AdminPageTitle icon={<BookmarkIcon size={32} />} title="Document Sets" />

      <Main />
    </div>
  );
};

export default Page;
