import { toast } from "@opal/layouts";
import { useState } from "react";
import { useTranslations } from "next-intl";
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
import { Checkbox } from "@opal/components";
import { ScoreSection } from "../ScoreEditor";
import { truncateString } from "@/lib/utils";
import { clickOnKeyDown } from "@opal/utils";

const IsVisibleSection = ({
  document,
  onUpdate,
}: {
  document: DocumentBoostStatus;
  onUpdate: (response: Response) => void;
}) => {
  const t = useTranslations("admin.documents");

  async function setHidden(hidden: boolean) {
    onUpdate(await updateHiddenStatus(document.document_id, hidden));
  }

  return (
    <HoverPopup
      mainContent={
        document.hidden ? (
          <div
            role="button"
            tabIndex={0}
            aria-label={t("visibility.unhide.ariaLabel")}
            onKeyDown={clickOnKeyDown(() => void setHidden(false))}
            onClick={() => void setHidden(false)}
            className="flex text-error cursor-pointer hover:bg-accent-background-hovered py-1 px-2 w-fit rounded-full"
          >
            <div className="select-none">{t("visibility.hidden.label")}</div>
            <div className="ml-1 my-auto">
              <Checkbox checked={false} />
            </div>
          </div>
        ) : (
          <div
            role="button"
            tabIndex={0}
            aria-label={t("visibility.hide.ariaLabel")}
            onKeyDown={clickOnKeyDown(() => void setHidden(true))}
            onClick={() => void setHidden(true)}
            className="flex cursor-pointer hover:bg-accent-background-hovered py-1 px-2 w-fit rounded-full"
          >
            <div className="my-auto select-none">
              {t("visibility.visible.label")}
            </div>
            <div className="ml-1 my-auto">
              <Checkbox checked={true} />
            </div>
          </div>
        )
      }
      popupContent={
        <div className="text-xs">
          {document.hidden ? (
            <div className="flex">
              <FiEye className="my-auto mr-1" /> {t("visibility.unhide.label")}
            </div>
          ) : (
            <div className="flex">
              <FiEyeOff className="my-auto mr-1" />
              {t("visibility.hide.label")}
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
  const t = useTranslations("admin.documents");
  const [page, setPage] = useState(1);

  return (
    <div>
      <Table className="overflow-visible">
        <TableHeader>
          <TableRow>
            <TableHead>{t("feedback.table.name.header")}</TableHead>
            <TableHead>{t("feedback.table.searchable.header")}</TableHead>
            <TableHead>{t("feedback.table.score.header")}</TableHead>
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
                      className="text-blue-600 dark:text-blue-300"
                      href={document.link}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {truncateString(document.semantic_id, 100)}
                    </a>
                  </TableCell>
                  <TableCell>
                    <IsVisibleSection
                      document={document}
                      onUpdate={async (response) => {
                        if (response.ok) {
                          refresh();
                        } else {
                          toast.error(
                            t("feedback.updateHiddenFailed.toast", {
                              detail: await getErrorMsg(response),
                            })
                          );
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
