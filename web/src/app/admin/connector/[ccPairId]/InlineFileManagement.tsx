"use client";

import { useState, useRef } from "react";
import { Button } from "@opal/components";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Checkbox } from "@opal/components";
import {
  updateConnectorFiles,
  type ConnectorFileInfo,
} from "@/lib/fileConnector";
import { toast } from "@/hooks/useToast";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ThreeDotsLoader } from "@/components/Loading";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import {
  SvgCheck,
  SvgEdit,
  SvgFolderPlus,
  SvgPlusCircle,
  SvgX,
} from "@opal/icons";
import { formatBytes } from "@/lib/utils";
import { timestampToReadableDate } from "@/lib/dateUtils";

interface InlineFileManagementProps {
  connectorId: number;
  onRefresh: () => void;
}

export default function InlineFileManagement({
  connectorId,
  onRefresh,
}: InlineFileManagementProps) {
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
      toast.error(
        "不能移除连接器中的所有文件。如需这样做，请删除该连接器。"
      );
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

      toast.success(
        "文件已更新！文档索引正在后台更新。新文件会被索引，已移除文件会从搜索结果中清理。"
      );

      // Reset editing state
      setIsEditing(false);
      setSelectedFilesToRemove(new Set());
      setFilesToAdd([]);

      // Refresh data
      refreshFiles();
      onRefresh();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "更新文件失败"
      );
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
      <Text as="p" className="text-error">
        加载文件失败：{error.message}
      </Text>
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
        <Text as="p" mainUiBody>
          文件（{totalFiles} 个）
        </Text>
        <div className="flex gap-2">
          {!isEditing ? (
            <Button
              prominence="secondary"
              onClick={() => setIsEditing(true)}
              icon={SvgEdit}
            >
              编辑
            </Button>
          ) : (
            <>
              <Button
                disabled={isSaving}
                prominence="secondary"
                onClick={handleCancel}
                icon={SvgX}
              >
                取消
              </Button>
              <Button
                disabled={
                  isSaving ||
                  (selectedFilesToRemove.size === 0 && filesToAdd.length === 0)
                }
                onClick={handleSaveClick}
                icon={SvgCheck}
              >
                {isSaving ? "正在保存..." : "保存更改"}
              </Button>
            </>
          )}
        </div>
      </div>

      {/* File List */}
      {files.length === 0 && filesToAdd.length === 0 ? (
        <Text as="p" mainUiMuted className="text-center py-8">
          此连接器中没有文件
        </Text>
      ) : (
        <div className="border rounded-lg overflow-hidden mb-4">
          {/* Scrollable container with max height */}
          <div className="max-h-[400px] overflow-y-auto">
            <Table>
              <TableHeader className="sticky top-0 bg-background z-10">
                <TableRow>
                  {isEditing && <TableHead className="w-12"></TableHead>}
                  <TableHead>文件名</TableHead>
                  <TableHead>大小</TableHead>
                  <TableHead>上传日期</TableHead>
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
                      <TableCell className="font-medium">
                        <span
                          className={
                            isMarkedForRemoval ? "line-through opacity-60" : ""
                          }
                        >
                          {file.file_name}
                        </span>
                        {isMarkedForRemoval && (
                          <span className="ml-2 text-xs font-semibold text-red-600 dark:text-red-400">
                            正在移除
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
                        {file.upload_date
                          ? timestampToReadableDate(file.upload_date)
                          : "-"}
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
                        <Button
                          icon={SvgX}
                          variant="danger"
                          prominence="tertiary"
                          size="sm"
                          onClick={() => handleRemoveNewFile(index)}
                          tooltip="移除文件"
                          title="移除文件"
                        />
                      </TableCell>
                    )}
                    <TableCell className="font-medium">
                      {file.name}
                      <Text as="p" figureSmallValue>
                        新增
                      </Text>
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
            disabled={isSaving}
            prominence="secondary"
            onClick={() => fileInputRef.current?.click()}
            icon={SvgPlusCircle}
          >
            添加文件
          </Button>
        </div>
      )}

      {/* Confirmation Modal */}
      <Modal open={showSaveConfirm} onOpenChange={setShowSaveConfirm}>
        <Modal.Content width="sm">
          <Modal.Header
            icon={SvgFolderPlus}
            title="确认文件更改"
            description="保存这些更改后，将发生以下操作："
          />

          <Modal.Body>
            {selectedFilesToRemove.size > 0 && (
              <div className="p-3 bg-red-50 dark:bg-red-900/10 rounded-md">
                <Text
                  as="p"
                  mainUiBody
                  className="font-semibold text-red-800 dark:text-red-200"
                >
                  将移除 {selectedFilesToRemove.size} 个文件
                </Text>
                <Text
                  as="p"
                  secondaryBody
                  className="text-red-700 dark:text-red-300 mt-1"
                >
                  这些文件中的文档会从文档索引中清理。
                </Text>
              </div>
            )}

            {filesToAdd.length > 0 && (
              <div className="p-3 bg-green-50 dark:bg-green-900/10 rounded-md">
                <Text
                  as="p"
                  mainUiBody
                  className="font-semibold text-green-800 dark:text-green-200"
                >
                  将添加 {filesToAdd.length} 个文件
                </Text>
                <Text
                  as="p"
                  secondaryBody
                  className="text-green-700 dark:text-green-300 mt-1"
                >
                  新文件会被上传、分块、嵌入，并写入文档索引。
                </Text>
              </div>
            )}
          </Modal.Body>

          <Modal.Footer>
            <Button
              disabled={isSaving}
              prominence="secondary"
              onClick={() => setShowSaveConfirm(false)}
            >
              取消
            </Button>
            <Button disabled={isSaving} onClick={handleConfirmSave}>
              {isSaving ? "正在保存..." : "确认并保存"}
            </Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </>
  );
}
