"use client";

import useSWR, { useSWRConfig } from "swr";

import { BasicTable } from "@/components/admin/connectors/BasicTable";
import { LoadingAnimation } from "@/components/Loading";
import { timeAgo } from "@/lib/time";
import { NotebookIcon } from "@/components/icons/icons";
import { fetcher } from "@/lib/fetcher";
import { IndexAttempt } from "@/components/admin/connectors/types";
import { getSourceMetadata } from "@/components/source";
import { CheckCircle, XCircle } from "@phosphor-icons/react";
import { submitIndexRequest } from "@/components/admin/connectors/IndexForm";
import { useState } from "react";
import { Popup } from "@/components/admin/connectors/Popup";
import { HealthCheckBanner } from "@/components/health/healthcheck";

const getSourceDisplay = (indexAttempt: IndexAttempt) => {
  const sourceMetadata = getSourceMetadata(indexAttempt.source);
  if (indexAttempt.source === "web") {
    return (
      sourceMetadata.displayName +
      (indexAttempt.connector_specific_config?.base_url &&
        ` [${indexAttempt.connector_specific_config?.base_url}]`)
    );
  }

  if (indexAttempt.source === "github") {
    return (
      sourceMetadata.displayName +
      ` [${indexAttempt.connector_specific_config?.repo_owner}/${indexAttempt.connector_specific_config?.repo_name}]`
    );
  }

  return sourceMetadata.displayName;
};

export default function Status() {
  const { mutate } = useSWRConfig();
  const {
    data: indexAttemptData,
    isLoading: indexAttemptIsLoading,
    error: indexAttemptIsError,
  } = useSWR<IndexAttempt[]>("/api/admin/latest-index-attempt", fetcher);

  const [popup, setPopup] = useState<{
    message: string;
    type: "success" | "error";
  } | null>(null);

  return (
    <div className="mx-auto container">
      {popup && <Popup message={popup.message} type={popup.type} />}
      <div className="mb-4">
        <HealthCheckBanner />
      </div>
      <div className="border-solid border-gray-600 border-b pb-2 mb-4 flex">
        <NotebookIcon size="32" />
        <h1 className="text-3xl font-bold pl-2">Indexing Status</h1>
      </div>

      {indexAttemptIsLoading ? (
        <LoadingAnimation text="Loading" />
      ) : indexAttemptIsError || !indexAttemptData ? (
        <div>Error loading indexing history</div>
      ) : (
        <BasicTable
          columns={[
            { header: "Connector", key: "connector" },
            { header: "Status", key: "status" },
            { header: "Last Indexed", key: "indexed_at" },
            { header: "Docs Indexed", key: "docs_indexed" },
            { header: "Re-Index", key: "reindex" },
          ]}
          data={indexAttemptData.map((indexAttempt) => {
            const sourceMetadata = getSourceMetadata(indexAttempt.source);
            let statusDisplay = (
              <div className="text-gray-400">In Progress...</div>
            );
            if (indexAttempt.status === "success") {
              statusDisplay = (
                <div className="text-green-600 flex">
                  <CheckCircle className="my-auto mr-1" size="18" />
                  Success
                </div>
              );
            } else if (indexAttempt.status === "failed") {
              statusDisplay = (
                <div className="text-red-600 flex">
                  <XCircle className="my-auto mr-1" size="18" />
                  Error
                </div>
              );
            }
            return {
              indexed_at: timeAgo(indexAttempt?.time_updated) || "-",
              docs_indexed: indexAttempt?.docs_indexed
                ? `${indexAttempt?.docs_indexed} documents`
                : "-",
              connector: (
                <a
                  className="text-blue-500 flex"
                  href={sourceMetadata.adminPageLink}
                >
                  {sourceMetadata.icon({ size: "20" })}
                  <div className="ml-1">{getSourceDisplay(indexAttempt)}</div>
                </a>
              ),
              status: statusDisplay,
              reindex: (
                <button
                  className={
                    "group relative " +
                    "py-1 px-2 border border-transparent text-sm " +
                    "font-medium rounded-md text-white bg-red-800 " +
                    "hover:bg-red-900 focus:outline-none focus:ring-2 " +
                    "focus:ring-offset-2 focus:ring-red-500 mx-auto"
                  }
                  onClick={async () => {
                    const { message, isSuccess } = await submitIndexRequest(
                      indexAttempt.source,
                      indexAttempt.connector_specific_config
                    );
                    setPopup({
                      message,
                      type: isSuccess ? "success" : "error",
                    });
                    setTimeout(() => {
                      setPopup(null);
                    }, 3000);
                    mutate("/api/admin/connector/index-attempt");
                  }}
                >
                  Index
                </button>
              ),
            };
          })}
        />
      )}
    </div>
  );
}
