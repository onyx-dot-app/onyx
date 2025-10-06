"use client";

import { useState, useRef } from "react";
import Button from "@/refresh-components/buttons/Button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Checkbox } from "@/components/ui/checkbox";
import {
  updateConnectorFiles,
  type ConnectorFileInfo,
} from "@/lib/fileConnector";
import { usePopup } from "@/components/admin/connectors/Popup";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ThreeDotsLoader } from "@/components/Loading";
import { Modal } from "@/components/Modal";
import Text from "@/components/ui/text";
import SvgEdit from "@/icons/edit";
import SvgCheck from "@/icons/check";
import SvgX from "@/icons/x";
import SvgPlusCircle from "@/icons/plus-circle";
import { formatBytes } from "@/lib/utils";

interface InlineFileManagementProps {
  connectorId: number;
  onRefresh: () => void;
}

function formatDate(dateString: string | undefined): string {
  if (!dateString) return "Unknown";
  try {
    const date = new Date(dateString);
    return date.toLocaleDateString() + " " + date.toLocaleTimeString();
  } catch {
    return "Unknown";
  }
}

export function InlineFileManagement({
  connectorId,
  onRefresh,
}: InlineFileManagementProps) {
  const { setPopup } = usePopup();
  const [isEditing, setIsEditing] = useState(false);
  const [selectedFilesToRemove, setSelectedFilesToRemove] = useState<
    Set<string>
  >(new Set());
  const [filesToAdd, setFilesToAdd] = useState<File[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [showSaveConfirm, setShowSaveConfirm] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const {
    data: filesResponse,
    isLoading,
    error,
    mutate: refreshFiles,
  } = useSWR<{ files: ConnectorFileInfo[] }>(
    `/api/manage/admin/connector/${connectorId}/files`,
    errorHandlingFetcher,
    { refreshInterval: isEditing ? 0 : 5000 } // Disable auto-refresh while editing
  );

  const files = filesResponse?.files || [];

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = event.target.files;
    if (!selectedFiles || selectedFiles.length === 0) return;

    setFilesToAdd((prev) => [...prev, ...Array.from(selectedFiles)]);
    // Reset the input
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleRemoveNewFile = (index: number) => {
    setFilesToAdd((prev) => prev.filter((_, i) => i !== index));
  };

  const toggleFileForRemoval = (fileId: string) => {
    setSelectedFilesToRemove((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(fileId)) {
        newSet.delete(fileId);
      } else {
        newSet.add(fileId);
      }
      return newSet;
    });
  };

  const handleSaveClick = () => {
    // Validate that we won't remove all files
    const remainingFiles = files.filter(
      (file) => !selectedFilesToRemove.has(file.file_id)
    ).length;

    if (remainingFiles === 0 && filesToAdd.length === 0) {
      setPopup({
        message: "Cannot remove all files. At least one file must remain.",
        type: "error",
      });
      return;
    }

    // Show confirmation modal
    setShowSaveConfirm(true);
  };

  const handleConfirmSave = async () => {
    setShowSaveConfirm(false);
    setIsSaving(true);
    try {
      await updateConnectorFiles(
        connectorId,
        Array.from(selectedFilesToRemove),
        filesToAdd
      );

      setPopup({
        message:
          "Files updated successfully! Vespa index is being updated in the background. " +
          "New files are being indexed and removed files will be pruned from the search results.",
        type: "success",
      });

      // Reset editing state
      setIsEditing(false);
      setSelectedFilesToRemove(new Set());
      setFilesToAdd([]);

      // Refresh data
      refreshFiles();
      onRefresh();
    } catch (error) {
      setPopup({
        message:
          error instanceof Error ? error.message : "Failed to update files",
        type: "error",
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleCancel = () => {
    setIsEditing(false);
    setSelectedFilesToRemove(new Set());
    setFilesToAdd([]);
  };

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <ThreeDotsLoader />
      </div>
    );
  }

  if (error) {
    return (
      <Text className="text-error">Error loading files: {error.message}</Text>
    );
  }

  const currentFiles = files.filter(
    (file) => !selectedFilesToRemove.has(file.file_id)
  );
  const totalFiles = currentFiles.length + filesToAdd.length;

  return (
    <>
      {/* Header with Edit/Save buttons */}
      <div className="flex justify-between items-center mb-4">
        <div className="text-sm font-medium">
          Files ({totalFiles} file{totalFiles !== 1 ? "s" : ""})
        </div>
        <div className="flex gap-2">
          {!isEditing ? (
            <Button
              onClick={() => setIsEditing(true)}
              secondary
              leftIcon={SvgEdit}
            >
              Edit
            </Button>
          ) : (
            <>
              <Button
                onClick={handleCancel}
                secondary
                leftIcon={SvgX}
                disabled={isSaving}
              >
                Cancel
              </Button>
              <Button
                onClick={handleSaveClick}
                primary
                leftIcon={SvgCheck}
                disabled={
                  isSaving ||
                  (selectedFilesToRemove.size === 0 && filesToAdd.length === 0)
                }
              >
                {isSaving ? "Saving..." : "Save Changes"}
              </Button>
            </>
          )}
        </div>
      </div>

      {/* File List */}
      {files.length === 0 && filesToAdd.length === 0 ? (
        <div className="text-center py-8 text-text-500">
          No files in this connector
        </div>
      ) : (
        <div className="border rounded-lg overflow-hidden mb-4">
          {/* Scrollable container with max height */}
          <div className="max-h-[400px] overflow-y-auto">
            <Table>
              <TableHeader className="sticky top-0 bg-background z-10">
                <TableRow>
                  {isEditing && <TableHead className="w-12"></TableHead>}
                  <TableHead>File Name</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead>Upload Date</TableHead>
                  {isEditing && <TableHead className="w-12"></TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {/* Existing files */}
                {files.map((file) => {
                  const isMarkedForRemoval = selectedFilesToRemove.has(
                    file.file_id
                  );
                  return (
                    <TableRow
                      key={file.file_id}
                      className={
                        isMarkedForRemoval
                          ? "bg-red-100 dark:bg-red-900/20"
                          : ""
                      }
                    >
                      {isEditing && (
                        <TableCell>
                          <Checkbox
                            checked={isMarkedForRemoval}
                            onCheckedChange={() =>
                              toggleFileForRemoval(file.file_id)
                            }
                          />
                        </TableCell>
                      )}
                      <TableCell
                        className={
                          isMarkedForRemoval ? "font-medium" : "font-medium"
                        }
                      >
                        <span
                          className={
                            isMarkedForRemoval ? "line-through opacity-60" : ""
                          }
                        >
                          {file.file_name}
                        </span>
                        {isMarkedForRemoval && (
                          <span className="ml-2 text-xs font-semibold text-red-600 dark:text-red-400">
                            Removing
                          </span>
                        )}
                      </TableCell>
                      <TableCell
                        className={
                          isMarkedForRemoval ? "line-through opacity-60" : ""
                        }
                      >
                        {formatBytes(file.file_size)}
                      </TableCell>
                      <TableCell
                        className={
                          isMarkedForRemoval ? "line-through opacity-60" : ""
                        }
                      >
                        {formatDate(file.upload_date)}
                      </TableCell>
                      {isEditing && <TableCell></TableCell>}
                    </TableRow>
                  );
                })}

                {/* New files to be added */}
                {filesToAdd.map((file, index) => (
                  <TableRow
                    key={`new-${index}`}
                    className="bg-green-50 dark:bg-green-900/10"
                  >
                    {isEditing && (
                      <TableCell>
                        <button
                          onClick={() => handleRemoveNewFile(index)}
                          className="h-4 w-4 flex items-center justify-center rounded hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors"
                          title="Remove this file"
                        >
                          <SvgX className="h-4 w-4 stroke-red-600 dark:stroke-red-400" />
                        </button>
                      </TableCell>
                    )}
                    <TableCell className="font-medium">
                      {file.name}
                      <span className="ml-2 text-xs text-green-600 dark:text-green-400">
                        New
                      </span>
                    </TableCell>
                    <TableCell>{formatBytes(file.size)}</TableCell>
                    <TableCell>-</TableCell>
                    {isEditing && <TableCell></TableCell>}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      {/* Add Files Button (only in edit mode) */}
      {isEditing && (
        <div className="mt-4">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={handleFileSelect}
            className="hidden"
            id={`file-upload-${connectorId}`}
          />
          <Button
            onClick={() => fileInputRef.current?.click()}
            secondary
            leftIcon={SvgPlusCircle}
            disabled={isSaving}
          >
            Add Files
          </Button>
        </div>
      )}

      {/* Confirmation Modal */}
      {showSaveConfirm && (
        <Modal onOutsideClick={() => setShowSaveConfirm(false)}>
          <>
            <div className="mb-4">
              <h2 className="text-xl font-bold mb-2">Confirm File Changes</h2>
              <Text className="text-sm">
                When you save these changes, the following will happen:
              </Text>
            </div>

            <div className="mb-6 space-y-3">
              {selectedFilesToRemove.size > 0 && (
                <div className="p-3 bg-red-50 dark:bg-red-900/10 rounded-md">
                  <Text className="text-sm font-semibold text-red-800 dark:text-red-200">
                    🗑️ {selectedFilesToRemove.size} file(s) will be removed
                  </Text>
                  <Text className="text-xs text-red-700 dark:text-red-300 mt-1">
                    Documents from these files will be pruned from Vespa search
                    index
                  </Text>
                </div>
              )}

              {filesToAdd.length > 0 && (
                <div className="p-3 bg-green-50 dark:bg-green-900/10 rounded-md">
                  <Text className="text-sm font-semibold text-green-800 dark:text-green-200">
                    ➕ {filesToAdd.length} file(s) will be added
                  </Text>
                  <Text className="text-xs text-green-700 dark:text-green-300 mt-1">
                    New files will be uploaded, chunked, embedded, and indexed
                    in Vespa
                  </Text>
                </div>
              )}
            </div>

            <div className="flex gap-3 justify-end">
              <Button
                onClick={() => setShowSaveConfirm(false)}
                secondary
                disabled={isSaving}
              >
                Cancel
              </Button>
              <Button onClick={handleConfirmSave} primary disabled={isSaving}>
                {isSaving ? "Saving..." : "Confirm & Save"}
              </Button>
            </div>
          </>
        </Modal>
      )}
    </>
  );
}
