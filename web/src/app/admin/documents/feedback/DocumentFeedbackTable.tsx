"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../i18n/keys";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useState, useEffect } from "react";
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
import { downloadItem } from "@/services/documentsService";

const IsVisibleSection = ({
  document,
  onUpdate,
}: {
  document: DocumentBoostStatus;
  onUpdate: (response: Response) => void;
}) => {
  const { t } = useTranslation();
  const [optimisticHidden, setOptimisticHidden] = useState<boolean | null>(
    null
  );
  const [isUpdating, setIsUpdating] = useState(false);

  // Сбрасываем оптимистичное состояние при изменении document.hidden (после refresh)
  useEffect(() => {
    if (!isUpdating) {
      setOptimisticHidden(null);
    }
  }, [document.hidden, isUpdating]);

  const isHidden =
    optimisticHidden !== null ? optimisticHidden : document.hidden;

  const handleToggle = async () => {
    if (isUpdating) return;

    const newHidden = !isHidden;
    setOptimisticHidden(newHidden);
    setIsUpdating(true);

    try {
      const response = await updateHiddenStatus(
        document.document_id,
        newHidden
      );
      onUpdate(response);
      if (!response.ok) {
        // Откатываем оптимистичное обновление при ошибке
        setOptimisticHidden(null);
      }
    } catch (error) {
      // Откатываем оптимистичное обновление при ошибке
      setOptimisticHidden(null);
    } finally {
      setIsUpdating(false);
    }
  };

  return (
    <HoverPopup
      mainContent={
        <div
          onClick={handleToggle}
          className={`flex items-center gap-2 cursor-pointer hover:bg-accent-background-hovered py-1 px-2 w-fit rounded-full ${
            isUpdating ? "opacity-50 pointer-events-none" : ""
          }`}
        >
          <div
            className={`select-none whitespace-nowrap ${
              isHidden ? "text-error" : ""
            }`}
          >
            {isHidden ? t(k.HIDDEN) : t(k.VISIBLE)}
          </div>
          <div className="flex-shrink-0">
            <CustomCheckbox checked={!isHidden} />
          </div>
        </div>
      }
      popupContent={
        <div className="text-xs">
          {isHidden ? (
            <div className="flex">
              <FiEye className="my-auto mr-1" /> {t(k.UNHIDE)}
            </div>
          ) : (
            <div className="flex">
              <FiEyeOff className="my-auto mr-1" />
              {t(k.HIDE)}
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
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const { popup, setPopup } = usePopup();
  const [downloadingIds, setDownloadingIds] = useState<Set<string>>(new Set());

  const handleDownload = async (doc: DocumentBoostStatus) => {
    if (downloadingIds.has(doc.document_id)) {
      return; // Prevent multiple simultaneous downloads
    }

    setDownloadingIds((prev) => new Set(prev).add(doc.document_id));

    try {
      const { blob, filename } = await downloadItem(doc.document_id);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename || doc.semantic_id || "document";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error("Failed to download document:", error);
      setPopup({
        message: `${t(k.ERROR_DOWNLOADING_DOCUMENT)}: ${
          error instanceof Error ? error.message : String(error)
        }`,
        type: "error",
      });
    } finally {
      setDownloadingIds((prev) => {
        const next = new Set(prev);
        next.delete(doc.document_id);
        return next;
      });
    }
  };

  return (
    <div>
      <Table className="overflow-visible">
        <TableHeader>
          <TableRow>
            <TableHead>{t(k.DOCUMENT_NAME)}</TableHead>
            <TableHead>{t(k.IS_SEARCHABLE)}</TableHead>
            <TableHead>{t(k.SCORE)}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {documents
            .slice((page - 1) * numToDisplay, page * numToDisplay)
            .map((doc) => {
              return (
                <TableRow key={doc.document_id}>
                  <TableCell className="whitespace-normal break-all">
                    <button
                      onClick={() => handleDownload(doc)}
                      disabled={downloadingIds.has(doc.document_id)}
                      className="text-blue-600 hover:text-blue-800 hover:underline disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                    >
                      {doc.semantic_id}
                    </button>
                  </TableCell>
                  <TableCell>
                    <IsVisibleSection
                      document={doc}
                      onUpdate={async (response) => {
                        if (response.ok) {
                          refresh();
                        } else {
                          setPopup({
                            message: `${t(
                              k.ERROR_UPDATING_HIDDEN_STATUS
                            )} ${await getErrorMsg(response, t)}`,
                            type: "error",
                          });
                        }
                      }}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="relative">
                      <div key={doc.document_id} className="h-10 ml-auto mr-8">
                        <ScoreSection
                          documentId={doc.document_id}
                          initialScore={doc.boost}
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
