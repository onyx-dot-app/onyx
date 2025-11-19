import { FileDescriptor } from "../interfaces";
import { ProjectFile } from "../projects/projectsService";

export function projectsFileToFileDescriptor(
  file: ProjectFile
): FileDescriptor {
  return {
    id: file.file_id,
    type: file.chat_file_type,
    name: file.name,
  };
}

export function projectFilesToFileDescriptors(
  files: ProjectFile[]
): FileDescriptor[] {
  return files.map(projectsFileToFileDescriptor);
}
