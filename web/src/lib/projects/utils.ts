import type { FileDescriptor } from "@/app/app/types";
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

/** A sent message's file as a composer attachment. */
export function fileDescriptorToProjectFile(file: FileDescriptor): ProjectFile {
  return {
    id: file.user_file_id ?? file.id,
    file_id: file.id,
    name: file.name ?? "",
    project_id: null,
    user_id: null,
    created_at: "",
    status: UserFileStatus.COMPLETED,
    file_type: "",
    last_accessed_at: "",
    chat_file_type: file.type,
    token_count: null,
    chunk_count: null,
  };
}

/** The files a retry of a sent message sends: its own, then the composer's. */
export function resendFiles(
  sent: { files?: FileDescriptor[] },
  composerFiles: ProjectFile[]
): ProjectFile[] {
  return [
    ...(sent.files ?? []).map(fileDescriptorToProjectFile),
    ...composerFiles,
  ];
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
