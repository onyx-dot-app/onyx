import {
  type Packet,
  PacketType,
  type PublishedFile,
} from "@/app/app/services/streamingModels";
import type { BackendChatSession } from "@/app/app/types";
import type { MessageTreeState } from "@/app/app/services/messageTree";
import { type CachedRead, readOnce } from "@/lib/chat/packetReads";
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
 * What the chat's loads gave of its published files: the server's list, null
 * until a load has one, and the IDs of the files in the packets that the
 * loads replayed.
 */
export interface LoadedPublishedFiles {
  listed: readonly PublishedFile[] | null;
  replayedFileIds: ReadonlySet<string>;
}

export const NO_LOADED_PUBLISHED_FILES: LoadedPublishedFiles = {
  listed: null,
  replayedFileIds: new Set(),
};

/** Adds a load of the chat. A load with a list replaces the list. */
export function addLoadedPublishedFiles(
  loaded: LoadedPublishedFiles,
  load: Pick<BackendChatSession, "published_files" | "packets">
): LoadedPublishedFiles {
  return {
    listed: load.published_files ?? loaded.listed,
    replayedFileIds: new Set([
      ...loaded.replayedFileIds,
      ...load.packets.flatMap((packets) =>
        readPublishedFiles(packets).map((file) => file.file_id)
      ),
    ]),
  };
}

/**
 * The chat's published files, on every branch: the newest publish of each
 * path, newest first. They are the server's list, then the files that packets
 * published after the loads, such as live publishes. A replayed file that the
 * list leaves out stays out: an older copy, a file whose object is missing or
 * a file without a stamped path. Without a list, the packets give the files.
 */
export function chatPublishedFiles(
  loaded: LoadedPublishedFiles,
  messageTree: MessageTreeState
): PublishedFile[] {
  const packetFiles = [...messageTree.values()].flatMap((message) =>
    readPublishedFiles(message.packets)
  );
  const files =
    loaded.listed === null
      ? packetFiles
      : [
          ...loaded.listed,
          ...packetFiles.filter(
            (file) => !loaded.replayedFileIds.has(file.file_id)
          ),
        ];
  const seenFileIds = new Set<string>();
  const newestByPath = new Map<string, PublishedFile>();
  for (const file of files) {
    if (seenFileIds.has(file.file_id)) continue;
    seenFileIds.add(file.file_id);
    // Deleting first moves the path to the end: the newest publish
    newestByPath.delete(file.path);
    newestByPath.set(file.path, file);
  }
  return [...newestByPath.values()].reverse();
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
