import {
  type Packet,
  PacketType,
  type PublishedFile,
} from "@/app/app/services/streamingModels";
import type { ChatPublishedFile, Message } from "@/app/app/types";
import type { MessageTreeState } from "@/app/app/services/messageTree";
import { type CachedRead, readOnce } from "@/lib/chat/packetReads";
import { rightPanelFileTab } from "@/lib/chat/rightPanel";
import { stripBidiControls } from "@opal/utils";

const publishedFileReads = new WeakMap<Packet[], CachedRead<PublishedFile[]>>();
const PUBLISH_END_PACKETS: ReadonlySet<string> = new Set([
  PacketType.PUBLISH_FILES_END,
]);

/** The files that one response's publish_files calls published, in order. */
function readPublishedFiles(packets: Packet[]): PublishedFile[] {
  return readOnce(publishedFileReads, packets, PUBLISH_END_PACKETS, (packets) =>
    packets.flatMap((packet) =>
      packet.obj.type === PacketType.PUBLISH_FILES_END ? packet.obj.files : []
    )
  );
}

/**
 * Every file published on the selected branch, oldest first, each file ID
 * once.
 *
 * `branchFiles` is the latest load's list for the branch, oldest first. It
 * also holds the files of messages that are not loaded and of the branch's
 * background subagents. A load entry of a loaded message that is no longer on
 * the branch, after a branch switch, is left out. The packets of the loaded
 * branch, oldest first, add the files that the load does not list. Those
 * after the last listed one are newer, such as live publishes. Those before
 * it are older, such as files saved without a path.
 */
function publishedFilesOnBranch(
  branchFiles: readonly ChatPublishedFile[],
  messageTree: MessageTreeState,
  branch: readonly Message[]
): PublishedFile[] {
  const branchMessageIds = new Set(branch.map((message) => message.messageId));
  const offBranchMessageIds = new Set(
    [...messageTree.values()]
      .map((message) => message.messageId)
      .filter((messageId) => !branchMessageIds.has(messageId))
  );
  const listed = branchFiles.filter(
    (file) => !offBranchMessageIds.has(file.message_id)
  );
  const listedIds = new Set(listed.map((file) => file.file_id));
  const packetFiles = branch.flatMap((message) =>
    readPublishedFiles(message.packets)
  );
  const lastListed = packetFiles.findLastIndex((file) =>
    listedIds.has(file.file_id)
  );
  const seenFileIds = new Set<string>();
  return [
    ...packetFiles
      .slice(0, lastListed + 1)
      .filter((file) => !listedIds.has(file.file_id)),
    ...listed,
    ...packetFiles.slice(lastListed + 1),
  ].filter((file) => {
    if (seenFileIds.has(file.file_id)) return false;
    seenFileIds.add(file.file_id);
    return true;
  });
}

/** The branch's published files: all of them, oldest first, and the newest
 * publish of each path, newest first, as the Files list shows them. */
export function branchPublishedFiles(
  branchFiles: readonly ChatPublishedFile[],
  messageTree: MessageTreeState,
  branch: readonly Message[]
): { all: PublishedFile[]; latest: PublishedFile[] } {
  const all = publishedFilesOnBranch(branchFiles, messageTree, branch);
  const newestByPath = new Map<string, PublishedFile>();
  for (const file of all) {
    // Deleting first moves the path to the end: the newest publish
    newestByPath.delete(file.path);
    newestByPath.set(file.path, file);
  }
  return { all, latest: [...newestByPath.values()].reverse() };
}

/**
 * A published file's shown name: its title, unless blank, else its name,
 * without bidi controls. Show it in an element with `dir="auto"`, unless it
 * is the only text of its flex item.
 */
export function publishedFileLabel(
  file: Pick<PublishedFile, "title" | "name">
): string {
  return stripBidiControls(file.title?.trim() || file.name);
}

/**
 * A published file's shown path, without bidi controls. Show it in an element
 * with `dir="ltr"`.
 */
export function publishedFilePath(
  file: Pick<PublishedFile, "display_path">
): string {
  return stripBidiControls(file.display_path);
}

/**
 * The files whose shown name another of `files` shares. They also show their
 * path, which tells them apart.
 */
export function filesSharingALabel(
  files: readonly PublishedFile[]
): Set<string> {
  const counts = new Map<string, number>();
  for (const file of files) {
    const label = publishedFileLabel(file);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return new Set(
    files
      .filter((file) => (counts.get(publishedFileLabel(file)) ?? 0) > 1)
      .map((file) => file.file_id)
  );
}

/** The files of the open file tabs, in tab order, from all the files. */
export function openFilesOfTabs(
  tabIds: readonly string[],
  allFiles: readonly PublishedFile[]
): PublishedFile[] {
  return tabIds.flatMap((tabId) => {
    const file = allFiles.find(
      (candidate) => rightPanelFileTab(candidate.file_id) === tabId
    );
    return file ? [file] : [];
  });
}
