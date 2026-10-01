import type { FileDescriptor } from "@/app/app/interfaces";
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
