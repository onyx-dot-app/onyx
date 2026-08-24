"use client";

import { useState, useCallback, useRef, useMemo, useEffect } from "react";
import useFocusOnMount from "@opal/hooks/useFocusOnMount";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  fetchLibraryTree,
  uploadLibraryFiles,
  uploadLibraryZip,
  createLibraryDirectory,
  deleteLibraryFile,
} from "@/app/craft/services/apiServices";
import { LibraryEntry } from "@/app/craft/types/user-library";
import { Modal } from "@opal/components";
import { cn, clickOnKeyDown } from "@opal/utils";
import {
  SvgFolder,
  SvgFolderOpen,
  SvgChevronRight,
  SvgChevronDown,
  SvgUploadCloud,
  SvgTrash,
  SvgFileText,
  SvgFolderPlus,
} from "@opal/icons";
import { Button, InputTypeIn, ShadowDiv, Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";

import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";

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

/** Keep entries whose name matches, plus folders with any matching descendant. */
function filterTree(entries: LibraryEntry[], query: string): LibraryEntry[] {
  const result: LibraryEntry[] = [];
  for (const entry of entries) {
    const children = entry.children ? filterTree(entry.children, query) : [];
    if (entry.name.toLowerCase().includes(query) || children.length > 0) {
      result.push({ ...entry, children });
    }
  }
  return result;
}

function formatFileSize(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface UserLibraryModalProps {
  open: boolean;
  onClose: () => void;
  onChanges?: () => void; // Called when files are uploaded or deleted
}

export default function UserLibraryModal({
  open,
  onClose,
  onChanges,
}: UserLibraryModalProps) {
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());
  const [isUploading, setIsUploading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [entryToDelete, setEntryToDelete] = useState<LibraryEntry | null>(null);
  const [showNewFolderModal, setShowNewFolderModal] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const focusOnMount = useFocusOnMount<HTMLInputElement>();
  const [searchQuery, setSearchQuery] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadTargetPathRef = useRef<string>("/");
  // dragenter/dragleave fire for every child element; count depth so the
  // overlay only clears when the cursor truly leaves the drop region.
  const dragDepth = useRef(0);

  // Fetch library tree
  const {
    data: tree,
    error,
    isLoading,
    mutate,
  } = useSWR(open ? SWR_KEYS.buildUserLibraryTree : null, fetchLibraryTree, {
    revalidateOnFocus: false,
  });

  // Build hierarchical tree from flat list
  const hierarchicalTree = useMemo(() => {
    if (!tree) return [];
    return buildTreeFromFlatList(tree);
  }, [tree]);

  const trimmedQuery = searchQuery.trim().toLowerCase();
  const visibleTree = useMemo(
    () =>
      trimmedQuery
        ? filterTree(hierarchicalTree, trimmedQuery)
        : hierarchicalTree,
    [hierarchicalTree, trimmedQuery]
  );

  // Reset transient state when the modal closes, so a drag interrupted by a
  // close doesn't leave the overlay stuck and a stale search doesn't hide
  // files on reopen.
  useEffect(() => {
    if (!open) {
      dragDepth.current = 0;
      setIsDragging(false);
      setSearchQuery("");
      setActionError(null);
    }
  }, [open]);

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

  const uploadFiles = useCallback(
    async (fileArray: File[], targetPath: string) => {
      if (fileArray.length === 0) return;

      setIsUploading(true);
      setActionError(null);

      try {
        // A lone .zip is expanded server-side; everything else uploads as-is.
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
        onChanges?.();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setIsUploading(false);
      }
    },
    [mutate, onChanges]
  );

  const handleFileInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const files = event.target.files;
      if (!files || files.length === 0) return;
      const targetPath = uploadTargetPathRef.current;
      void uploadFiles(Array.from(files), targetPath).finally(() => {
        uploadTargetPathRef.current = "/";
        event.target.value = "";
      });
    },
    [uploadFiles]
  );

  const handleUploadToFolder = useCallback((folderPath: string) => {
    uploadTargetPathRef.current = folderPath;
    fileInputRef.current?.click();
  }, []);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    dragDepth.current += 1;
    setIsDragging(true);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    if (e.dataTransfer.types.includes("Files")) e.preventDefault();
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    dragDepth.current -= 1;
    if (dragDepth.current <= 0) {
      dragDepth.current = 0;
      setIsDragging(false);
    }
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      dragDepth.current = 0;
      setIsDragging(false);
      if (isUploading) return;
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) void uploadFiles(files, "/");
    },
    [uploadFiles, isUploading]
  );

  const handleDeleteConfirm = useCallback(async () => {
    if (!entryToDelete) return;

    try {
      await deleteLibraryFile(entryToDelete.id);
      setActionError(null);
      mutate();
      onChanges?.();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setEntryToDelete(null);
    }
  }, [entryToDelete, mutate, onChanges]);

  const handleCreateDirectory = useCallback(async () => {
    const name = newFolderName.trim();
    if (!name) return;

    try {
      await createLibraryDirectory({ name, parent_path: "/" });
      setActionError(null);
      mutate();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "Failed to create folder"
      );
    } finally {
      setShowNewFolderModal(false);
      setNewFolderName("");
    }
  }, [mutate, newFolderName]);

  const isEmpty = hierarchicalTree.length === 0;
  const noMatches = !isEmpty && visibleTree.length === 0;

  return (
    <>
      <Modal open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
        <Modal.Content width="sm" height="fit" preventAccidentalClose={false}>
          <Modal.Header
            icon={SvgFolder}
            title="Library"
            description="Files your agent can read in every session."
            onClose={onClose}
          >
            <Section flexDirection="row" gap={2}>
              <InputTypeIn
                placeholder="Search files..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                searchIcon
                autoComplete="off"
              />
              <Button
                prominence="secondary"
                icon={SvgFolderPlus}
                onClick={() => setShowNewFolderModal(true)}
                tooltip="New folder"
                aria-label="New folder"
              />
              <Button
                icon={SvgUploadCloud}
                disabled={isUploading}
                onClick={() => handleUploadToFolder("/")}
              >
                {isUploading ? "Uploading…" : "Upload"}
              </Button>
            </Section>
          </Modal.Header>
          <Modal.Body>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={handleFileInputChange}
              disabled={isUploading}
            />

            <div className="flex w-full flex-col gap-3">
              {actionError && (
                <div className="rounded-8 border border-status-error-02 bg-status-error-01 px-3 py-2">
                  <Text font="secondary-body" color="status-error-05">
                    {actionError}
                  </Text>
                </div>
              )}

              {/* Drop region — accepts file drops in both empty and populated states */}
              <div
                className="relative"
                onDragEnter={handleDragEnter}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
              >
                {isLoading ? (
                  <div className="flex items-center justify-center py-12">
                    <Text font="secondary-body" color="text-03">
                      Loading files…
                    </Text>
                  </div>
                ) : error ? (
                  <div className="flex items-center justify-center py-12">
                    <Text font="secondary-body" color="status-error-05">
                      Failed to load files
                    </Text>
                  </div>
                ) : isEmpty ? (
                  <UploadDropzone
                    onClick={() => handleUploadToFolder("/")}
                    active={isDragging}
                  />
                ) : noMatches ? (
                  <div className="flex items-center justify-center py-12">
                    <Text font="secondary-body" color="text-03">
                      No files match your search
                    </Text>
                  </div>
                ) : (
                  <ShadowDiv className="max-h-[360px]">
                    <div className="flex flex-col gap-0.5">
                      <LibraryTreeView
                        entries={visibleTree}
                        expandedPaths={expandedPaths}
                        forceExpanded={trimmedQuery.length > 0}
                        onToggleFolder={toggleFolder}
                        onDelete={setEntryToDelete}
                        onUploadToFolder={handleUploadToFolder}
                      />
                    </div>
                  </ShadowDiv>
                )}

                {/* Drag overlay — consistent feedback regardless of state */}
                {isDragging && (
                  <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-12 border-2 border-dashed border-action-selection-04 bg-action-selection-01/90">
                    <Text font="main-ui-action" color="text-05">
                      Drop files to upload
                    </Text>
                  </div>
                )}
              </div>
            </div>
          </Modal.Body>

          <Modal.Footer>
            <Button prominence="secondary" onClick={onClose}>
              Done
            </Button>
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
            title="New folder"
            onClose={() => {
              setShowNewFolderModal(false);
              setNewFolderName("");
            }}
          />
          <Modal.Body>
            <div className="flex flex-col items-stretch gap-2">
              <Text font="secondary-body" color="text-03">
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
                ref={focusOnMount}
              />
            </div>
          </Modal.Body>
          <Modal.Footer>
            <Button
              prominence="secondary"
              onClick={() => {
                setShowNewFolderModal(false);
                setNewFolderName("");
              }}
            >
              Cancel
            </Button>
            <Button
              disabled={!newFolderName.trim()}
              onClick={handleCreateDirectory}
            >
              Create
            </Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </>
  );
}

interface UploadDropzoneProps {
  onClick: () => void;
  active: boolean;
}

function UploadDropzone({ onClick, active }: UploadDropzoneProps) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === " " || e.key === "Enter") {
          e.preventDefault();
          onClick();
        }
      }}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-12 border border-dashed px-6 py-10 text-center transition-colors",
        active
          ? "border-action-selection-04 bg-action-selection-01"
          : "border-border-03 bg-background-tint-02 hover:border-action-selection-04 hover:bg-action-selection-01"
      )}
    >
      <SvgUploadCloud size={28} className="stroke-text-03" />
      <Text font="main-ui-action" color="text-04">
        Drag files here or click to upload
      </Text>
      <Text font="secondary-body" color="text-03">
        Excel, Word, PowerPoint, PDF, or ZIP
      </Text>
    </div>
  );
}

interface LibraryTreeViewProps {
  entries: LibraryEntry[];
  expandedPaths: Set<string>;
  /** Expand every folder regardless of `expandedPaths` (used while searching). */
  forceExpanded: boolean;
  onToggleFolder: (path: string) => void;
  onDelete: (entry: LibraryEntry) => void;
  onUploadToFolder: (folderPath: string) => void;
  depth?: number;
}

function LibraryTreeView({
  entries,
  expandedPaths,
  forceExpanded,
  onToggleFolder,
  onDelete,
  onUploadToFolder,
  depth = 0,
}: LibraryTreeViewProps) {
  // Sort entries: directories first, then alphabetically
  const sortedEntries = [...entries].sort((a, b) => {
    if (a.is_directory && !b.is_directory) return -1;
    if (!a.is_directory && b.is_directory) return 1;
    return a.name.localeCompare(b.name);
  });

  // Only reserve chevron space when this level mixes folders and files.
  const hasDirectories = sortedEntries.some((entry) => entry.is_directory);

  return (
    <>
      {sortedEntries.map((entry) => {
        const isExpanded = forceExpanded || expandedPaths.has(entry.path);

        const rowClassName = cn(
          "group flex items-center gap-2 rounded-8 px-2 py-1.5 transition-colors hover:bg-background-tint-01",
          entry.is_directory && "cursor-pointer"
        );

        const rowBody = (
          <>
            {/* Indent for nesting depth */}
            {depth > 0 && (
              <span
                aria-hidden
                className="shrink-0"
                style={{ width: `${depth * 1.25}rem` }}
              />
            )}

            {/* Expand/collapse for directories (icon swap avoids a rotate style) */}
            {entry.is_directory ? (
              <Button
                prominence="tertiary"
                size="2xs"
                icon={isExpanded ? SvgChevronDown : SvgChevronRight}
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleFolder(entry.path);
                }}
                tooltip={isExpanded ? "Collapse" : "Expand"}
                aria-label={isExpanded ? "Collapse" : "Expand"}
              />
            ) : (
              hasDirectories && <span aria-hidden className="w-5 shrink-0" />
            )}

            {/* Type icon */}
            {entry.is_directory ? (
              isExpanded ? (
                <SvgFolderOpen size={16} className="shrink-0 stroke-text-03" />
              ) : (
                <SvgFolder size={16} className="shrink-0 stroke-text-03" />
              )
            ) : (
              <SvgFileText size={16} className="shrink-0 stroke-text-03" />
            )}

            {/* Name */}
            <div className="min-w-0 flex-1">
              <Text font="main-ui-muted" color="text-04" maxLines={1}>
                {entry.name}
              </Text>
            </div>

            {/* File size */}
            {!entry.is_directory && entry.file_size !== null && (
              <Text font="secondary-body" color="text-03" nowrap>
                {formatFileSize(entry.file_size)}
              </Text>
            )}

            {/* Row actions — revealed on hover/focus */}
            <div className="flex items-center gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100 no-hover:opacity-100">
              {entry.is_directory && (
                <Button
                  prominence="tertiary"
                  size="sm"
                  icon={SvgUploadCloud}
                  onClick={(e) => {
                    e.stopPropagation();
                    const uploadPath =
                      entry.path.replace(/^user_library/, "") || "/";
                    onUploadToFolder(uploadPath);
                  }}
                  tooltip="Upload to this folder"
                  aria-label="Upload to this folder"
                />
              )}
              <Button
                variant="danger"
                prominence="tertiary"
                size="sm"
                icon={SvgTrash}
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(entry);
                }}
                tooltip="Delete"
                aria-label="Delete"
              />
            </div>
          </>
        );

        return (
          <div key={entry.id} className="flex flex-col">
            {entry.is_directory ? (
              // The row holds its own buttons, so a clickable folder row stays
              // a div with button semantics rather than a nested <button>.
              <div
                className={rowClassName}
                role="button"
                tabIndex={0}
                aria-label={`Toggle ${entry.name}`}
                onKeyDown={clickOnKeyDown(() => onToggleFolder(entry.path))}
                onClick={() => onToggleFolder(entry.path)}
              >
                {rowBody}
              </div>
            ) : (
              <div className={rowClassName}>{rowBody}</div>
            )}

            {/* Children */}
            {entry.is_directory && isExpanded && entry.children && (
              <LibraryTreeView
                entries={entry.children}
                expandedPaths={expandedPaths}
                forceExpanded={forceExpanded}
                onToggleFolder={onToggleFolder}
                onDelete={onDelete}
                onUploadToFolder={onUploadToFolder}
                depth={depth + 1}
              />
            )}
          </div>
        );
      })}
    </>
  );
}
