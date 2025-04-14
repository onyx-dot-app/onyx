import i18n from "i18next";
import k from "./../../../../i18n/keys";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useState } from "react";
import {
  Table,
  TableHead,
  TableRow,
  TableHeader,
  TableBody,
  TableCell,
} from "@/components/ui/table";
import { PageSelector } from "@/components/PageSelector";
import { DocumentBoostStatus } from "@/lib/types";
import { updateHiddenStatus } from "../lib";
import { numToDisplay } from "./constants";
import { FiEye, FiEyeOff } from "react-icons/fi";
import { getErrorMsg } from "@/lib/fetchUtils";
import { HoverPopup } from "@/components/HoverPopup";
import { CustomCheckbox } from "@/components/CustomCheckbox";
import { ScoreSection } from "../ScoreEditor";

const IsVisibleSection = ({
  document,
  onUpdate,
}: {
  document: DocumentBoostStatus;
  onUpdate: (response: Response) => void;
}) => {
  return (
    <HoverPopup
      mainContent={
        document.hidden ? (
          <div
            onClick={async () => {
              const response = await updateHiddenStatus(
                document.document_id,
                false
              );
              onUpdate(response);
            }}
            className="flex text-error cursor-pointer hover:bg-accent-background-hovered py-1 px-2 w-fit rounded-full"
          >
            <div className="select-none">{i18n.t(k.HIDDEN)}</div>
            <div className="ml-1 my-auto">
              <CustomCheckbox checked={false} />
            </div>
          </div>
        ) : (
          <div
            onClick={async () => {
              const response = await updateHiddenStatus(
                document.document_id,
                true
              );
              onUpdate(response);
            }}
            className="flex cursor-pointer hover:bg-accent-background-hovered py-1 px-2 w-fit rounded-full"
          >
            <div className="my-auto select-none">{i18n.t(k.VISIBLE)}</div>
            <div className="ml-1 my-auto">
              <CustomCheckbox checked={true} />
            </div>
          </div>
        )
      }
      popupContent={
        <div className="text-xs">
          {document.hidden ? (
            <div className="flex">
              <FiEye className="my-auto mr-1" /> {i18n.t(k.UNHIDE)}
            </div>
          ) : (
            <div className="flex">
              <FiEyeOff className="my-auto mr-1" />
              {i18n.t(k.HIDE)}
            </div>
          )}
        </div>
      }
      direction="left"
    />
  );
};

export const DocumentFeedbackTable = ({
  documents,
  refresh,
}: {
  documents: DocumentBoostStatus[];
  refresh: () => void;
}) => {
  const [page, setPage] = useState(1);
  const { popup, setPopup } = usePopup();

  return (
    <div>
      <Table className="overflow-visible">
        <TableHeader>
          <TableRow>
            <TableHead>{i18n.t(k.DOCUMENT_NAME)}</TableHead>
            <TableHead>{i18n.t(k.IS_SEARCHABLE)}</TableHead>
            <TableHead>{i18n.t(k.SCORE)}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {documents
            .slice((page - 1) * numToDisplay, page * numToDisplay)
            .map((document) => {
              return (
                <TableRow key={document.document_id}>
                  <TableCell className="whitespace-normal break-all">
                    <a
                      className="text-blue-600"
                      href={document.link}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {document.semantic_id}
                    </a>
                  </TableCell>
                  <TableCell>
                    <IsVisibleSection
                      document={document}
                      onUpdate={async (response) => {
                        if (response.ok) {
                          refresh();
                        } else {
                          setPopup({
                            message: `${i18n.t(
                              k.ERROR_UPDATING_HIDDEN_STATUS
                            )} ${getErrorMsg(response)}`,
                            type: "error",
                          });
                        }
                      }}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="relative">
                      <div
                        key={document.document_id}
                        className="h-10 ml-auto mr-8"
                      >
                        <ScoreSection
                          documentId={document.document_id}
                          initialScore={document.boost}
                          refresh={refresh}
                          setPopup={setPopup}
                        />
                      </div>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
        </TableBody>
      </Table>

      <div className="mt-3 flex">
        <div className="mx-auto">
          <PageSelector
            totalPages={Math.ceil(documents.length / numToDisplay)}
            currentPage={page}
            onPageChange={(newPage) => setPage(newPage)}
          />
        </div>
      </div>
    </div>
  );
};
