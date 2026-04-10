"use client";

import { useState } from "react";
import useSWR from "swr";
import { Text, Card, Tag } from "@opal/components";
import { Button } from "@opal/components/buttons/button/components";
import { SvgExternalLink, SvgFileText, SvgX } from "@opal/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { IllustrationContent } from "@opal/layouts";
import SvgEmpty from "@opal/illustrations/empty";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import DocumentUpload from "@/app/proposal-review/components/DocumentUpload";
import type {
  Proposal,
  ProposalDocument,
  ProposalStatus,
} from "@/app/proposal-review/types";
import type { TagColor } from "@opal/components";

// ---------------------------------------------------------------------------
// Status → Tag
// ---------------------------------------------------------------------------

const STATUS_TAG: Record<ProposalStatus, { color: TagColor; label: string }> = {
  PENDING: { color: "gray", label: "Pending" },
  IN_REVIEW: { color: "blue", label: "In Review" },
  APPROVED: { color: "green", label: "Approved" },
  CHANGES_REQUESTED: { color: "amber", label: "Changes Requested" },
  REJECTED: { color: "amber", label: "Rejected" },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface MetadataRowProps {
  label: string;
  value: string | undefined;
}

function MetadataRow({ label, value }: MetadataRowProps) {
  if (!value) return null;
  return (
    <div className="flex justify-between gap-2 py-1">
      <Text font="secondary-body" color="text-03" nowrap>
        {label}
      </Text>
      <Text font="main-ui-body" color="text-01" as="span">
        {value}
      </Text>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ProposalInfoPanelProps {
  proposal: Proposal;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ProposalInfoPanel({
  proposal,
}: ProposalInfoPanelProps) {
  const { metadata, status, id: proposalId } = proposal;
  const statusConfig = STATUS_TAG[status];
  const [selectedDoc, setSelectedDoc] = useState<ProposalDocument | null>(null);

  // Fetch documents
  const {
    data: documents,
    isLoading: docsLoading,
    mutate: mutateDocs,
  } = useSWR<ProposalDocument[]>(
    `/api/proposal-review/proposals/${proposalId}/documents`,
    errorHandlingFetcher
  );

  return (
    <div className="flex flex-col gap-4 h-full overflow-y-auto p-4">
      {/* Proposal metadata card */}
      <Card padding="md" border="solid" background="light">
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <Text font="main-ui-action" color="text-01">
              Proposal Details
            </Text>
            <Tag title={statusConfig.label} color={statusConfig.color} />
          </div>

          <div className="flex flex-col">
            {/* Jira key — link out if URL available */}
            {metadata.jira_key && (
              <div className="flex justify-between gap-2 py-1">
                <Text font="secondary-body" color="text-03" nowrap>
                  Jira Key
                </Text>
                {metadata.link ? (
                  <a
                    href={metadata.link}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-action-link-01 hover:text-action-link-02"
                  >
                    <Text font="main-ui-body" color="inherit" as="span">
                      {metadata.jira_key}
                    </Text>
                    <SvgExternalLink className="h-3 w-3" />
                  </a>
                ) : (
                  <Text font="main-ui-body" color="text-01" as="span">
                    {metadata.jira_key}
                  </Text>
                )}
              </div>
            )}

            <MetadataRow label="Title" value={metadata.title} />
            <MetadataRow label="PI" value={metadata.pi_name} />
            <MetadataRow label="Sponsor" value={metadata.sponsor} />
            <MetadataRow label="Deadline" value={metadata.deadline} />
            <MetadataRow
              label="Agreement Type"
              value={metadata.agreement_type}
            />
            <MetadataRow label="Officer" value={metadata.officer} />
          </div>
        </div>
      </Card>

      {/* Documents section */}
      <Card padding="md" border="solid" background="light">
        <div className="flex flex-col gap-3">
          <Text font="main-ui-action" color="text-01">
            Documents
          </Text>

          {docsLoading && (
            <div className="flex items-center justify-center py-4">
              <SimpleLoader />
            </div>
          )}

          {!docsLoading && (!documents || documents.length === 0) && (
            <IllustrationContent
              illustration={SvgEmpty}
              title="No documents"
              description="Upload a document to get started."
            />
          )}

          {documents && documents.length > 0 && (
            <div className="flex flex-col gap-1">
              {documents.map((doc) => (
                <div
                  key={doc.id}
                  className="flex items-center gap-2 py-2 px-2 rounded-08 hover:bg-background-neutral-02 cursor-pointer"
                  onClick={() =>
                    setSelectedDoc(selectedDoc?.id === doc.id ? null : doc)
                  }
                >
                  <SvgFileText className="h-4 w-4 text-text-03 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <Text font="main-ui-body" color="text-01" nowrap>
                      {doc.file_name}
                    </Text>
                  </div>
                  <Tag title={doc.document_role} color="gray" size="sm" />
                </div>
              ))}
            </div>
          )}

          {/* Document text viewer */}
          {selectedDoc && (
            <Card padding="md" border="dashed" background="light">
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <Text font="secondary-action" color="text-02">
                    {selectedDoc.file_name}
                  </Text>
                  <Button
                    variant="default"
                    prominence="tertiary"
                    size="xs"
                    icon={SvgX}
                    onClick={() => setSelectedDoc(null)}
                  />
                </div>
                <div className="max-h-[300px] overflow-y-auto rounded-08 bg-background-neutral-01 p-3">
                  {selectedDoc.extracted_text ? (
                    <Text font="secondary-mono" color="text-02" as="p">
                      {selectedDoc.extracted_text}
                    </Text>
                  ) : (
                    <Text font="secondary-body" color="text-03" as="p">
                      No extracted text available for this document.
                    </Text>
                  )}
                </div>
              </div>
            </Card>
          )}

          <DocumentUpload
            proposalId={proposalId}
            onUploadComplete={() => mutateDocs()}
          />
        </div>
      </Card>
    </div>
  );
}
