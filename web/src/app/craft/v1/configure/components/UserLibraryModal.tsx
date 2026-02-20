"use client";

import { useState, useCallback, useRef, useMemo } from "react";
import useSWR from "swr";
import {
  fetchLibraryTree,
  uploadLibraryFiles,
  uploadLibraryZip,
  createLibraryDirectory,
  toggleLibraryFileSync,
  deleteLibraryFile,
} from "@/app/craft/services/apiServices";
import { LibraryEntry } from "@/app/craft/types/user-library";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import Modal from "@/refresh-components/Modal";
import ShadowDiv from "@/refresh-components/ShadowDiv";
import { Section } from "@/layouts/general-layouts";
import {
  SvgFolder,
  SvgFolderOpen,
  SvgChevronRight,
  SvgUploadCloud,
  SvgTrash,
  SvgFileText,
  SvgFolderPlus,
} from "@opal/icons";
import Switch from "@/refresh-components/inputs/Switch";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";
import IconButton from "@/refresh-components/buttons/IconButton";

/**
 * Build a hierarchical tree from a flat list of library entries.
 * Entries have paths like "user_library/test" or "user_library/test/file.pdf"
 */
function buildTreeFromFlatList(flatList: LibraryEntry[]): LibraryEntry[] {
  // Create a map of path -> entry (with children array initialized)
  const pathToEntry = new Map<string, LibraryEntry>();

  // First pass: create entries with empty children arrays
  for (const entry of flatList) {
    pathToEntry.set(entry.path, { ...entry, children: [] });
  }

  // Second pass: build parent-child relationships
  const rootEntries: LibraryEntry[] = [];

  for (const entry of flatList) {
    const entryWithChildren = pathToEntry.get(entry.path)!;

    // Find parent path by removing the last segment
    const pathParts = entry.path.split("/");
    pathParts.pop(); // Remove last segment (filename or folder name)
    const parentPath = pathParts.join("/");

    const parent = pathToEntry.get(parentPath);
    if (parent && parent.children) {
      parent.children.push(entryWithChildren);
    } else {
      // No parent found, this is a root-level entry
      rootEntries.push(entryWithChildren);
    }
  }

  return rootEntries;
}

interface UserLibraryModalProps {
  open: boolean;
  onClose: () => void;
  onChanges?: () => void; // Called when files are uploaded, deleted, or sync toggled
}

export default function UserLibraryModal({
  open,
  onClose,
  onChanges,
}: UserLibraryModalProps) {
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [entryToDelete, setEntryToDelete] = useState<LibraryEntry | null>(null);
  const [showNewFolderModal, setShowNewFolderModal] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadTargetPathRef = useRef<string>("/");

  // Fetch library tree
  const {
    data: tree,
    error,
    isLoading,
    mutate,
  } = useSWR(open ? "/api/build/user-library/tree" : null, fetchLibraryTree, {
    revalidateOnFocus: false,
  });

  // Build hierarchical tree from flat list
  const hierarchicalTree = useMemo(() => {
    if (!tree) return [];
    return buildTreeFromFlatList(tree);
  }, [tree]);

  const toggleFolder = useCallback((path: string) => {
    setExpandedPaths((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(path)) {
        newSet.delete(path);
      } else {
        newSet.add(path);
      }
      return newSet;
    });
  }, []);

  const handleFileUpload = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const files = event.target.files;
      if (!files || files.length === 0) return;

      setIsUploading(true);
      setUploadError(null);

      const targetPath = uploadTargetPathRef.current;

      try {
        const fileArray = Array.from(files);
        // Check if it's a single zip file
        const firstFile = fileArray[0];
        if (
          fileArray.length === 1 &&
          firstFile &&
          firstFile.name.endsWith(".zip")
        ) {
          await uploadLibraryZip(targetPath, firstFile);
        } else {
          await uploadLibraryFiles(targetPath, fileArray);
        }
        mutate();
        onChanges?.(); // Notify parent that changes were made
      } catch (err) {
        setUploadError(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setIsUploading(false);
        uploadTargetPathRef.current = "/";
        // Reset input
        event.target.value = "";
      }
    },
    [mutate, onChanges]
  );

  const handleUploadToFolder = useCallback((folderPath: string) => {
    uploadTargetPathRef.current = folderPath;
    fileInputRef.current?.click();
  }, []);

  const handleToggleSync = useCallback(
    async (entry: LibraryEntry, enabled: boolean) => {
      try {
        await toggleLibraryFileSync(entry.id, enabled);
        mutate();
        onChanges?.(); // Notify parent that changes were made
      } catch (err) {
        console.error("Failed to toggle sync:", err);
      }
    },
    [mutate, onChanges]
  );

  const handleDeleteConfirm = useCallback(async () => {
    if (!entryToDelete) return;

    try {
      await deleteLibraryFile(entryToDelete.id);
      mutate();
      onChanges?.(); // Notify parent that changes were made
    } catch (err) {
      console.error("Failed to delete:", err);
    } finally {
      setEntryToDelete(null);
    }
  }, [entryToDelete, mutate, onChanges]);

  const handleCreateDirectory = useCallback(async () => {
    const name = newFolderName.trim();
    if (!name) return;

    try {
      await createLibraryDirectory({ name, parent_path: "/" });
      mutate();
    } catch (err) {
      console.error("Failed to create directory:", err);
      setUploadError(
        err instanceof Error ? err.message : "Failed to create folder"
      );
    } finally {
      setShowNewFolderModal(false);
      setNewFolderName("");
    }
  }, [mutate, newFolderName]);

  const formatFileSize = (bytes: number | null): string => {
    if (bytes === null) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const fileCount = hierarchicalTree.length;

  return (
    <>
      <Modal open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
        <Modal.Content width="md" height="fit">
          <Modal.Header
            icon={SvgFileText}
            title="Your Files"
            description="Upload files for your agent to read (Excel, Word, PowerPoint, etc.)"
            onClose={onClose}
          />
          <Modal.Body>
            <Section flexDirection="column" gap={1} alignItems="stretch">
              {/* Upload error */}
              {uploadError && (
                <Section
                  flexDirection="row"
                  alignItems="center"
                  justifyContent="start"
                  padding={0.5}
                  height="fit"
                >
                  <Text secondaryBody>{uploadError}</Text>
                </Section>
              )}

              {/* File explorer */}
              <Section flexDirection="column" alignItems="stretch">
                {/* Action buttons */}
                <Section
                  flexDirection="row"
                  justifyContent="end"
                  gap={0.5}
                  padding={0.5}
                >
                  <IconButton
                    icon={SvgFolderPlus}
                    onClick={() => setShowNewFolderModal(true)}
                    secondary
                    tooltip="New Folder"
                  />
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    style={{ display: "none" }}
                    onChange={handleFileUpload}
                    disabled={isUploading}
                    accept=".xlsx,.xls,.docx,.doc,.pptx,.ppt,.csv,.json,.txt,.pdf,.zip"
                  />
                  <IconButton
                    icon={SvgUploadCloud}
                    onClick={() => handleUploadToFolder("/")}
                    disabled={isUploading}
                    tooltip={isUploading ? "Uploading..." : "Upload"}
                    aria-label={isUploading ? "Uploading..." : "Upload"}
                    secondary
                  />
                </Section>

                {isLoading ? (
                  <Section padding={2} height="fit">
                    <Text secondaryBody text03>
                      Loading files...
                    </Text>
                  </Section>
                ) : error ? (
                  <Section padding={2} height="fit">
                    <Text secondaryBody text03>
                      Failed to load files
                    </Text>
                  </Section>
                ) : fileCount === 0 ? (
                  <Section padding={2} height="fit" gap={0.5}>
                    <SvgFileText size={32} className="stroke-text-02" />
                    <Text secondaryBody text03>
                      No files uploaded yet
                    </Text>
                    <Text secondaryBody text02>
                      Upload Excel, Word, PowerPoint, or other files for your
                      agent to work with
                    </Text>
                  </Section>
                ) : (
                  <ShadowDiv style={{ maxHeight: "400px", padding: "0.5rem" }}>
                    <LibraryTreeView
                      entries={hierarchicalTree}
                      expandedPaths={expandedPaths}
                      onToggleFolder={toggleFolder}
                      onToggleSync={handleToggleSync}
                      onDelete={setEntryToDelete}
                      onUploadToFolder={handleUploadToFolder}
                      formatFileSize={formatFileSize}
                    />
                  </ShadowDiv>
                )}
              </Section>
            </Section>
          </Modal.Body>

          <Modal.Footer>
            <Button onClick={onClose}>Done</Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>

      {/* Delete confirmation modal */}
      {entryToDelete && (
        <ConfirmEntityModal
          danger
          entityType={entryToDelete.is_directory ? "folder" : "file"}
          entityName={entryToDelete.name}
          action="delete"
          actionButtonText="Delete"
          additionalDetails={
            entryToDelete.is_directory
              ? "This will delete the folder and all its contents."
              : "This file will be removed from your library."
          }
          onClose={() => setEntryToDelete(null)}
          onSubmit={handleDeleteConfirm}
        />
      )}

      {/* New folder modal */}
      <Modal
        open={showNewFolderModal}
        onOpenChange={(isOpen) => {
          if (!isOpen) {
            setShowNewFolderModal(false);
            setNewFolderName("");
          }
        }}
      >
        <Modal.Content width="sm" height="fit">
          <Modal.Header
            icon={SvgFolder}
            title="New Folder"
            onClose={() => {
              setShowNewFolderModal(false);
              setNewFolderName("");
            }}
          />
          <Modal.Body>
            <Section flexDirection="column" gap={0.5} alignItems="stretch">
              <Text secondaryBody text03>
                Folder name
              </Text>
              <InputTypeIn
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                placeholder="Enter folder name"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newFolderName.trim()) {
                    handleCreateDirectory();
                  }
                }}
                autoFocus
              />
            </Section>
          </Modal.Body>
          <Modal.Footer>
            <Button
              secondary
              onClick={() => {
                setShowNewFolderModal(false);
                setNewFolderName("");
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={handleCreateDirectory}
              disabled={!newFolderName.trim()}
            >
              Create
            </Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </>
  );
}

interface LibraryTreeViewProps {
  entries: LibraryEntry[];
  expandedPaths: Set<string>;
  onToggleFolder: (path: string) => void;
  onToggleSync: (entry: LibraryEntry, enabled: boolean) => void;
  onDelete: (entry: LibraryEntry) => void;
  onUploadToFolder: (folderPath: string) => void;
  formatFileSize: (bytes: number | null) => string;
  depth?: number;
}

function LibraryTreeView({
  entries,
  expandedPaths,
  onToggleFolder,
  onToggleSync,
  onDelete,
  onUploadToFolder,
  formatFileSize,
  depth = 0,
}: LibraryTreeViewProps) {
  // Sort entries: directories first, then alphabetically
  const sortedEntries = [...entries].sort((a, b) => {
    if (a.is_directory && !b.is_directory) return -1;
    if (!a.is_directory && b.is_directory) return 1;
    return a.name.localeCompare(b.name);
  });

  return (
    <>
      {sortedEntries.map((entry) => {
        const isExpanded = expandedPaths.has(entry.path);

        return (
          <Section
            key={entry.id}
            flexDirection="column"
            alignItems="stretch"
            gap={0}
            height="fit"
          >
            <Section
              flexDirection="row"
              alignItems="center"
              justifyContent="start"
              gap={0.25}
              height="fit"
              padding={0.5}
            >
              {/* Indent spacer - inline style needed for dynamic depth */}
              {depth > 0 && (
                <span
                  aria-hidden
                  style={{
                    display: "inline-block",
                    width: `${depth * 1.25}rem`,
                    flexShrink: 0,
                  }}
                />
              )}

              {/* Expand/collapse for directories */}
              {entry.is_directory ? (
                <IconButton
                  icon={SvgChevronRight}
                  onClick={() => onToggleFolder(entry.path)}
                  small
                  tooltip={isExpanded ? "Collapse" : "Expand"}
                  style={{
                    transform: isExpanded ? "rotate(90deg)" : undefined,
                    transition: "transform 150ms ease",
                  }}
                />
              ) : (
                <Section width="fit" height="fit" gap={0} padding={0}>
                  <SvgChevronRight size={12} style={{ visibility: "hidden" }} />
                </Section>
              )}

              {/* Icon */}
              {entry.is_directory ? (
                isExpanded ? (
                  <SvgFolderOpen size={16} className="stroke-text-03" />
                ) : (
                  <SvgFolder size={16} className="stroke-text-03" />
                )
              ) : (
                <SvgFileText size={16} className="stroke-text-03" />
              )}

              {/* Name */}
              <Section
                flexDirection="row"
                alignItems="center"
                justifyContent="start"
                gap={0}
                height="fit"
              >
                <Text secondaryBody text04 className="truncate">
                  {entry.name}
                </Text>
              </Section>

              {/* File size */}
              {!entry.is_directory && entry.file_size !== null && (
                <Section width="fit" height="fit" gap={0} padding={0}>
                  <Text secondaryBody text02 style={{ whiteSpace: "nowrap" }}>
                    {formatFileSize(entry.file_size)}
                  </Text>
                </Section>
              )}

              {/* Actions */}
              <Section
                flexDirection="row"
                alignItems="center"
                justifyContent="end"
                gap={0.25}
                width="fit"
                height="fit"
              >
                {entry.is_directory && (
                  <IconButton
                    icon={SvgUploadCloud}
                    onClick={(e) => {
                      e.stopPropagation();
                      const uploadPath =
                        entry.path.replace(/^user_library/, "") || "/";
                      onUploadToFolder(uploadPath);
                    }}
                    small
                    tooltip="Upload to this folder"
                  />
                )}
                <IconButton
                  icon={SvgTrash}
                  onClick={() => onDelete(entry)}
                  small
                  danger
                  tooltip="Delete"
                />
              </Section>

              {/* Sync toggle */}
              <SimpleTooltip
                tooltip={
                  entry.sync_enabled
                    ? "Synced to sandbox - click to disable"
                    : "Not synced - click to enable"
                }
              >
                <Switch
                  checked={entry.sync_enabled}
                  onCheckedChange={(checked) => onToggleSync(entry, checked)}
                />
              </SimpleTooltip>
            </Section>

            {/* Children */}
            {entry.is_directory && isExpanded && entry.children && (
              <LibraryTreeView
                entries={entry.children}
                expandedPaths={expandedPaths}
                onToggleFolder={onToggleFolder}
                onToggleSync={onToggleSync}
                onDelete={onDelete}
                onUploadToFolder={onUploadToFolder}
                formatFileSize={formatFileSize}
                depth={depth + 1}
              />
            )}
          </Section>
        );
      })}
    </>
  );
}
