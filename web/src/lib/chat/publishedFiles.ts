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
 * until a load has one, the sequence of the load that gave the list, and the
 * IDs of the files in the packets that the loads replayed.
 */
export interface LoadedPublishedFiles {
  listed: readonly PublishedFile[] | null;
  listedBy: number;
  replayedFileIds: ReadonlySet<string>;
}

export const NO_LOADED_PUBLISHED_FILES: LoadedPublishedFiles = {
  listed: null,
  listedBy: 0,
  replayedFileIds: new Set(),
};

let chatLoadsStarted = 0;

/**
 * The sequence of a load of a chat page, taken as its fetch starts: a load
 * that starts later has a higher one. A page that the server rendered is
 * sequence 0.
 */
export function startChatLoad(): number {
  chatLoadsStarted += 1;
  return chatLoadsStarted;
}

/**
 * Adds a load of the chat, of sequence `loadSequence`. A load with a list
 * replaces the list unless a load that started later gave it.
 */
export function addLoadedPublishedFiles(
  loaded: LoadedPublishedFiles,
  load: Pick<BackendChatSession, "published_files" | "packets">,
  loadSequence: number
): LoadedPublishedFiles {
  const replaces =
    load.published_files != null && loadSequence >= loaded.listedBy;
  return {
    listed: replaces ? (load.published_files ?? null) : loaded.listed,
    listedBy: replaces ? loadSequence : loaded.listedBy,
    replayedFileIds: new Set([
      ...loaded.replayedFileIds,
      ...load.packets.flatMap((packets) =>
        readPublishedFiles(packets).map((file) => file.file_id)
      ),
    ]),
  };
}

/**
 * A published file's artifact: every publish of its path in the chat. A file
 * saved without an artifact is its own artifact.
 */
export function artifactKey(
  file: Pick<PublishedFile, "artifact_id" | "file_id">
): string {
  return file.artifact_id ?? file.file_id;
}

/**
 * Whether the Files list of the chat `chatId` holds `file`: a file of the
 * chat, or one saved without a chat.
 */
export function belongsToChat(
  file: Pick<PublishedFile, "chat_id">,
  chatId: string | null
): boolean {
  return file.chat_id == null || file.chat_id === chatId;
}

/**
 * The newest version of `file`'s artifact among `file` and `files`: `file`
 * itself unless `files` holds a higher version. A file without a version is
 * version 1.
 */
export function newestVersion(
  file: PublishedFile,
  files: readonly PublishedFile[]
): PublishedFile {
  const key = artifactKey(file);
  return files.reduce(
    (newest, other) =>
      artifactKey(other) === key && (other.version ?? 1) > (newest.version ?? 1)
        ? other
        : newest,
    file
  );
}

/**
 * The published files of the chat `chatId`, on every branch: the newest
 * version of each artifact, newest artifact first. They are the server's
 * list, then the files that packets published after the loads, such as live
 * publishes. A replayed file that the list leaves out stays out: an older
 * version, a file whose object is missing or a file saved without an
 * artifact. Without a list, the packets give the files. A version that the
 * chat added to another chat's artifact stays out, as the list leaves it
 * out; its reply card shows it.
 */
export function chatPublishedFiles(
  loaded: LoadedPublishedFiles,
  messageTree: MessageTreeState,
  chatId: string
): PublishedFile[] {
  const packetFiles = [...messageTree.values()].flatMap((message) =>
    readPublishedFiles(message.packets).filter((file) =>
      belongsToChat(file, chatId)
    )
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
  // An artifact keeps the place of its first file
  const newestByArtifact = new Map<string, PublishedFile>();
  for (const file of files) {
    const key = artifactKey(file);
    const known = newestByArtifact.get(key);
    if (!known || (file.version ?? 1) > (known.version ?? 1))
      newestByArtifact.set(key, file);
  }
  return [...newestByArtifact.values()].reverse();
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

/**
 * How the user may open an artifact link: `owner` in the owning chat,
 * `chat_reader` in that chat's shared view, `file_only` as the file alone
 * (a version that a chat the user can read holds).
 */
export type ChatArtifactAccess = "owner" | "chat_reader" | "file_only";

/** A version of a published file, with the chat that owns it. */
export interface ChatArtifactFile extends PublishedFile {
  chat_id: string;
  access: ChatArtifactAccess;
}

/** An artifact link's artifact and version (null: the newest). */
export interface ArtifactLink {
  artifactId: string;
  version: number | null;
}

// The path of an artifact link, `/app/artifacts/<artifact_id>[/v<N>]`, which
// the artifact tools give the model (backend `artifact_url`).
const ARTIFACT_LINK_PATH =
  /^\/app\/artifacts\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\/v(\d+))?\/?$/i;

/**
 * The artifact that `href` links to, on any origin, or null for any other
 * link. The backend's WEB_DOMAIN can differ from the page's origin, and the
 * metadata request checks access either way.
 */
export function parseArtifactLink(href: string): ArtifactLink | null {
  let pathname: string;
  try {
    pathname = new URL(href, "http://localhost").pathname;
  } catch {
    return null;
  }
  const match = ARTIFACT_LINK_PATH.exec(pathname);
  if (!match?.[1]) return null;
  return {
    artifactId: match[1],
    version: match[2] === undefined ? null : Number(match[2]),
  };
}
