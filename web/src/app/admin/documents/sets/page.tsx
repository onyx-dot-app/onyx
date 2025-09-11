"use client";
import i18n from "@/i18n/init";
import k from "./../../../../i18n/keys";

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
import { Button } from "@/components/ui/button";
import { DocumentSet } from "@/lib/types";
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
import Link from "next/link";
import { useRouter } from "next/navigation";
import { TableHeader } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import CreateButton from "@/components/ui/createButton";

const numToDisplay = 50;

const EditRow = ({
  documentSet,
  isEditable,
}: {
  documentSet: DocumentSet;
  isEditable: boolean;
}) => {
  const router = useRouter();

  if (!isEditable) {
    return (
      <div className="text-text-darkerfont-medium my-auto p-1">
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
              text-text-darkerfont-medium my-auto p-1 hover:bg-accent-background flex items-center select-none
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
                {i18n.t(k.CANNOT_UPDATE_WHILE_SYNCING_W)}
              </div>
            </TooltipContent>
          )}
        </Tooltip>
      </TooltipProvider>
    </div>
  );
};

interface DocumentFeedbackTableProps {
  documentSets: DocumentSet[];
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
      <Title>{i18n.t(k.EXISTING_DOCUMENT_SETS)}</Title>
      <Table className="overflow-visible mt-2">
        <TableHeader>
          <TableRow>
            <TableHead>{i18n.t(k.NAME)}</TableHead>
            <TableHead>{i18n.t(k.CONNECTORS)}</TableHead>
            <TableHead>{i18n.t(k.STATUS)}</TableHead>
            <TableHead>{i18n.t(k.PUBLIC)}</TableHead>
            <TableHead>{i18n.t(k.DELETE)}</TableHead>
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
                      <Badge variant="success" icon={FiCheckCircle}>
                        {i18n.t(k.UP_TO_DATE)}
                      </Badge>
                    ) : documentSet.cc_pair_descriptors.length > 0 ? (
                      <Badge variant="in_progress" icon={FiClock}>
                        {i18n.t(k.SYNCING)}
                      </Badge>
                    ) : (
                      <Badge variant="destructive" icon={FiAlertTriangle}>
                        {i18n.t(k.DELETING)}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {documentSet.is_public ? (
                      <Badge
                        variant={isEditable ? "success" : "default"}
                        icon={FiUnlock}
                      >
                        {i18n.t(k.PUBLIC)}
                      </Badge>
                    ) : (
                      <Badge
                        variant={isEditable ? "private" : "default"}
                        icon={FiLock}
                      >
                        {i18n.t(k.PRIVATE1)}
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
                              message: `${i18n.t(k.DOCUMENT_SET)}${
                                documentSet.name
                              }${i18n.t(k.SCHEDULED_FOR_DELETION)}`,
                              type: "success",
                            });
                          } else {
                            const errorMsg = (await response.json()).detail;
                            setPopup({
                              message: `${i18n.t(
                                k.FAILED_TO_SCHEDULE_DOCUMENT_SE
                              )} ${errorMsg}`,
                              type: "error",
                            });
                          }
                          refresh();
                          refreshEditable();
                        }}
                      />
                    ) : (
                      i18n.t(k._)
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
    return <ThreeDotsLoader />;
  }

  if (documentSetsError || !documentSets) {
    return (
      <div>
        {i18n.t(k.ERROR1)} {documentSetsError}
      </div>
    );
  }

  if (editableDocumentSetsError || !editableDocumentSets) {
    return (
      <div>
        {i18n.t(k.ERROR1)} {editableDocumentSetsError}
      </div>
    );
  }

  return (
    <div className="mb-8">
      {popup}
      <Text className="mb-3">
        <b>{i18n.t(k.DOCUMENT_SETS)}</b>{" "}
        {i18n.t(k.ALLOW_YOU_TO_GROUP_LOGICALLY_C)}
      </Text>

      <div className="mb-3"></div>

      <div className="flex mb-6">
        <CreateButton
          href="/admin/documents/sets/new"
          text={i18n.t(k.NEW_DOCUMENT_SET_BUTTON)}
        />

        {/* <Link href="/admin/documents/sets/new">
            <Button variant="navigate">New Document Set</Button>
           </Link> */}
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
      <AdminPageTitle
        icon={<BookmarkIcon size={32} />}
        title={i18n.t(k.DOCUMENT_SETS_TITLE)}
      />

      <Main />
    </div>
  );
};

export default Page;
