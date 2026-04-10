"use client";

import { useState, useRef } from "react";
import { Button, Text } from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { uploadDocument } from "@/app/proposal-review/services/apiServices";
import type { DocumentRole } from "@/app/proposal-review/types";

interface DocumentUploadProps {
  proposalId: string;
  onUploadComplete: () => void;
}

const DOCUMENT_ROLES: { value: DocumentRole; label: string }[] = [
  { value: "PROPOSAL", label: "Proposal" },
  { value: "BUDGET", label: "Budget" },
  { value: "FOA", label: "FOA" },
  { value: "INTERNAL", label: "Internal" },
  { value: "SOW", label: "Scope of Work" },
  { value: "OTHER", label: "Other" },
];

export default function DocumentUpload({
  proposalId,
  onUploadComplete,
}: DocumentUploadProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedRole, setSelectedRole] = useState<DocumentRole>("OTHER");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    setUploadError(null);

    try {
      await uploadDocument(proposalId, file, selectedRole);
      onUploadComplete();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setIsUploading(false);
      // Reset the file input so the same file can be re-selected
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <div className="flex-1">
          <InputSelect
            value={selectedRole}
            onValueChange={(v) => setSelectedRole(v as DocumentRole)}
          >
            <InputSelect.Trigger placeholder="Document role" />
            <InputSelect.Content>
              {DOCUMENT_ROLES.map((role) => (
                <InputSelect.Item key={role.value} value={role.value}>
                  {role.label}
                </InputSelect.Item>
              ))}
            </InputSelect.Content>
          </InputSelect>
        </div>

        <Button
          variant="default"
          prominence="secondary"
          icon={SvgUploadCloud}
          disabled={isUploading}
          onClick={() => fileInputRef.current?.click()}
        >
          {isUploading ? "Uploading..." : "Upload"}
        </Button>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        accept=".pdf,.docx,.xlsx,.html,.txt"
        onChange={handleFileSelect}
      />

      {uploadError && (
        <Text font="secondary-body" color="text-03">
          {uploadError}
        </Text>
      )}
    </div>
  );
}
