"use client";

import React, { useRef } from "react";
import { SvgUploadCloud } from "@opal/icons";
import { Button } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import Modal from "@/refresh-components/Modal";

interface ImportFlowProps {
  open: boolean;
  onClose: () => void;
  onFileSelected: (file: File) => void;
}

function ImportFlow({ open, onClose, onFileSelected }: ImportFlowProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }

    onFileSelected(file);
    onClose();
  }

  if (!open) return null;

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="sm" height="fit">
        <Modal.Header
          icon={SvgUploadCloud}
          title="Import from Checklist"
          description="Upload a checklist document to generate rules automatically."
          onClose={onClose}
        />
        <Modal.Body>
          <IllustrationContent
            illustration={SvgUploadCloud}
            title="Upload a checklist document (.xlsx, .docx, or .pdf)"
            description="The document will be analyzed and rules will be added as inactive drafts."
          />
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.docx,.pdf,.txt,.md"
            onChange={handleFileChange}
            className="hidden"
          />
          <div className="flex justify-center w-full">
            <Button
              icon={SvgUploadCloud}
              onClick={() => fileInputRef.current?.click()}
            >
              Choose File
            </Button>
          </div>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}

export default ImportFlow;
