import { ChatFileType, type FileDescriptor } from "@/app/app/interfaces";
import { type ProjectFile, UserFileStatus } from "@/lib/projects/types";

export function projectsFileToFileDescriptor(
  file: ProjectFile
): FileDescriptor {
  return {
    id: file.file_id,
    type: file.chat_file_type,
    name: file.name,
    user_file_id: file.id,
  };
}

export function projectFilesToFileDescriptors(
  files: ProjectFile[]
): FileDescriptor[] {
  return files.map(projectsFileToFileDescriptor);
}

/** True while a file is uploading or still being processed for use in chat. */
export function isFilePending(status: UserFileStatus): boolean {
  return (
    status === UserFileStatus.UPLOADING ||
    status === UserFileStatus.PROCESSING ||
    status === UserFileStatus.INDEXING
  );
}

/**
 * Share of the available context that attached files may fill before they
 * are only reachable through search. Mirrors `max_llm_context_percentage` in
 * the backend's `extract_context_files`.
 */
const INLINE_FILE_CONTEXT_FRACTION = 0.6;

/**
 * Why the attached files hold back sending:
 * - `uploading`: a file has not reached the server yet.
 * - `tooLarge`: the files do not fit in the context, so the model can only
 *   reach them through search once indexing completes.
 * - `noText`: a file has no extracted text yet (e.g. a scanned PDF waiting
 *   on image captions).
 */
export type FileSendBlock = "uploading" | "tooLarge" | "noText";

/** The blocks that wait on indexing and are explained in a banner. */
export type FileIndexingReason = Extract<FileSendBlock, "tooLarge" | "noText">;

/**
 * Returns why the attached files must finish indexing before the message is
 * sent, or null when it can go now. A file still processing does not block
 * on its own: its text is extracted at upload and sent inline.
 */
export function getFileSendBlock(
  files: ProjectFile[],
  availableContextTokens: number
): FileSendBlock | null {
  if (files.some((file) => file.status === UserFileStatus.UPLOADING)) {
    return "uploading";
  }
  const processing = files.filter((file) => isFilePending(file.status));
  if (processing.length === 0) {
    return null;
  }
  if (
    processing.some(
      (file) =>
        file.chat_file_type !== ChatFileType.TABULAR && !file.token_count
    )
  ) {
    return "noText";
  }
  // Spreadsheets are passed as metadata only, so they never fill the context.
  const inlineFiles = files.filter(
    (file) => file.chat_file_type !== ChatFileType.TABULAR
  );
  const fileTokens = inlineFiles.reduce(
    (total, file) => total + (file.token_count ?? 0),
    0
  );
  return fileTokens >= availableContextTokens * INLINE_FILE_CONTEXT_FRACTION
    ? "tooLarge"
    : null;
}
