// Mobile-native, per the PR 2 no-shared-chat-code decision (web keeps its own
// web/src/lib/projects/utils.ts). Key remap matches web's
// projectsFileToFileDescriptor exactly: file_id → id, chat_file_type → type,
// id → user_file_id.
import { UserFileStatus, type ProjectFile } from "@/chat/contracts/projects";
import type { FileDescriptor } from "@/chat/interfaces";

export function projectFileToFileDescriptor(file: ProjectFile): FileDescriptor {
  return {
    id: file.file_id,
    type: file.chat_file_type,
    name: file.name,
    user_file_id: file.id,
  };
}

export function projectFilesToFileDescriptors(
  files: ProjectFile[],
): FileDescriptor[] {
  return files.map(projectFileToFileDescriptor);
}

// Inverse: a sent message's descriptor → a display file record so the chip strip can
// render it read-only. A sent attachment is always indexed, hence COMPLETED.
export function fileDescriptorToDisplayFile(
  descriptor: FileDescriptor,
): ProjectFile {
  return {
    id: descriptor.user_file_id ?? descriptor.id,
    name: descriptor.name ?? "File",
    file_id: descriptor.id,
    status: UserFileStatus.COMPLETED,
    chat_file_type: descriptor.type,
    token_count: null,
    created_at: "",
  };
}
