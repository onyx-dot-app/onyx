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
 * A load's list of the branch's published files, oldest first. The list is
 * complete for the messages up to `throughMessageId` and leaves out files on
 * purpose, such as those whose object is missing.
 */
export interface LoadedPublishedFiles {
  files: readonly ChatPublishedFile[];
  throughMessageId: number;
}

/**
 * A load's list of published files, or null when the load has none. The list
 * covers every message of the load, except the answers of a run in flight:
 * the run saves their files when it ends, so the list stops before the run's
 * question, the newest user message.
 */
export function loadedPublishedFiles(load: {
  messages: readonly { message_id: number; message_type: string }[];
  published_files?: readonly ChatPublishedFile[];
  is_processing?: boolean;
  current_stream?: unknown;
}): LoadedPublishedFiles | null {
  if (!load.published_files) return null;
  const running = Boolean(load.is_processing || load.current_stream);
  const covered = running
    ? load.messages.filter((message) => message.message_type === "user")
    : load.messages;
  return {
    files: load.published_files,
    throughMessageId: Math.max(0, ...covered.map((m) => m.message_id)),
  };
}

/**
 * Every file published on the selected branch, oldest first, each file ID
 * once.
 *
 * The load's list is the files of every message that it knew of, also of
 * messages that are not loaded and of the branch's background subagents. A
 * list entry of a loaded message that is no longer on the branch, after a
 * branch switch, is left out. The packets add only the files of messages
 * newer than the load, such as live publishes. Without a list, the packets
 * give all the files.
 */
function publishedFilesOnBranch(
  loaded: LoadedPublishedFiles | null,
  messageTree: MessageTreeState,
  branch: readonly Message[]
): PublishedFile[] {
  const branchMessageIds = new Set(branch.map((message) => message.messageId));
  const offBranchMessageIds = new Set(
    [...messageTree.values()]
      .map((message) => message.messageId)
      .filter((messageId) => !branchMessageIds.has(messageId))
  );
  const listed = (loaded?.files ?? []).filter(
    (file) => !offBranchMessageIds.has(file.message_id)
  );
  const newer = branch
    .filter(
      (message) =>
        loaded === null ||
        message.messageId === undefined ||
        message.messageId > loaded.throughMessageId
    )
    .flatMap((message) => readPublishedFiles(message.packets));
  const seenFileIds = new Set<string>();
  return [...listed, ...newer].filter((file) => {
    if (seenFileIds.has(file.file_id)) return false;
    seenFileIds.add(file.file_id);
    return true;
  });
}

/** The branch's published files: all of them, oldest first, and the newest
 * publish of each path, newest first, as the Files list shows them. */
export function branchPublishedFiles(
  loaded: LoadedPublishedFiles | null,
  messageTree: MessageTreeState,
  branch: readonly Message[]
): { all: PublishedFile[]; latest: PublishedFile[] } {
  const all = publishedFilesOnBranch(loaded, messageTree, branch);
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
