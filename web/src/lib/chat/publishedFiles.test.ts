import {
  type Packet,
  PacketType,
  type PublishedFile,
} from "@/app/app/services/streamingModels";
import type { BackendChatSession, Message } from "@/app/app/types";
import {
  addLoadedPublishedFiles,
  chatPublishedFiles,
  filesSharingALabel,
  type LoadedPublishedFiles,
  NO_LOADED_PUBLISHED_FILES,
  newestVersion,
  publishedFileLabel,
} from "@/lib/chat/publishedFiles";

/** A publish of `path`: a version of the path's artifact. */
function published(
  fileId: string,
  path: string,
  version = 1,
  title: string | null = null
): PublishedFile {
  return {
    file_id: fileId,
    name: path.split("/").pop() ?? path,
    title,
    path,
    display_path: path,
    size: 10,
    mime_type: "text/markdown",
    artifact_id: `artifact${path}`,
    version,
    thumbnail_file_id: null,
  };
}

/** A file whose saved details have no artifact. */
function unversioned(fileId: string, path: string): PublishedFile {
  return { ...published(fileId, path), artifact_id: null, version: null };
}

function publishEnd(files: PublishedFile[], subTurnIndex?: number): Packet {
  return {
    placement: { turn_index: 0, tab_index: 0, sub_turn_index: subTurnIndex },
    obj: { type: PacketType.PUBLISH_FILES_END, files, error: null },
  };
}

function response(
  nodeId: number,
  messageId: number | undefined,
  packets: Packet[]
): Message {
  return {
    nodeId,
    messageId,
    type: "assistant",
    message: "",
    files: [],
    packets,
    toolCall: null,
    parentNodeId: null,
  };
}

function tree(messages: Message[]): Map<number, Message> {
  return new Map(messages.map((message) => [message.nodeId, message]));
}

/** What a load of `messages` with the server's list `listed` gives. */
function load(
  listed: PublishedFile[] | null | undefined,
  messages: Message[]
): LoadedPublishedFiles {
  const page: Pick<BackendChatSession, "published_files" | "packets"> = {
    published_files: listed,
    packets: messages.map((message) => message.packets),
  };
  return addLoadedPublishedFiles(NO_LOADED_PUBLISHED_FILES, page, 1);
}

const fileIds = (files: PublishedFile[]): string[] =>
  files.map((file) => file.file_id);

describe("chatPublishedFiles", () => {
  test("reads every publish_files result, nested calls included", () => {
    const packets = [
      publishEnd([published("a", "/w/report.md")]),
      publishEnd([published("b", "/w/chart.png")], 0),
    ];
    const answer = response(2, 2, packets);
    const files = () =>
      fileIds(chatPublishedFiles(NO_LOADED_PUBLISHED_FILES, tree([answer])));

    expect(files()).toEqual(["b", "a"]);

    // A stream appends to the same array.
    packets.push(publishEnd([published("c", "/w/notes.md")]));
    expect(files()).toEqual(["c", "b", "a"]);
  });

  test("keeps the newest version of each artifact, in its first publish's place", () => {
    const answer = response(2, 2, [
      publishEnd([
        published("a", "/w/report.md", 1, "Draft"),
        published("b", "/w/chart.png"),
      ]),
      publishEnd([published("c", "/w/report.md", 2)]),
      // A repeated report of one call adds nothing.
      publishEnd([published("c", "/w/report.md", 2)]),
    ]);

    expect(
      chatPublishedFiles(NO_LOADED_PUBLISHED_FILES, tree([answer])).map(
        ({ file_id, title }) => [file_id, title]
      )
    ).toEqual([
      ["b", null],
      ["c", null],
    ]);
  });

  test("a file saved without an artifact is its own artifact", () => {
    const answer = response(2, 2, [
      publishEnd([
        unversioned("old-a", "/w/report.md"),
        unversioned("old-b", "/w/report.md"),
      ]),
      publishEnd([published("new", "/w/report.md")]),
    ]);

    expect(
      fileIds(chatPublishedFiles(NO_LOADED_PUBLISHED_FILES, tree([answer])))
    ).toEqual(["new", "old-b", "old-a"]);
  });

  test("lists the files of every branch", () => {
    // Answers 2 and 3 answer question 1; the shown branch holds answer 3.
    const question: Message = {
      ...response(1, 1, []),
      type: "user",
      childrenNodeIds: [2, 3],
      latestChildNodeId: 3,
    };
    const switched = {
      ...response(2, 2, [publishEnd([published("switched", "/w/notes.md")])]),
      parentNodeId: 1,
    };
    const shown = {
      ...response(3, 3, [publishEnd([published("shown", "/w/report.md")])]),
      parentNodeId: 1,
    };
    const messages = [question, switched, shown];

    expect(
      fileIds(chatPublishedFiles(NO_LOADED_PUBLISHED_FILES, tree(messages)))
    ).toEqual(["shown", "switched"]);
    // The server's list holds a file of a branch that is not loaded too.
    expect(
      fileIds(
        chatPublishedFiles(
          load(
            [
              published("unloaded", "/w/chart.png"),
              published("switched", "/w/notes.md"),
              published("shown", "/w/report.md"),
            ],
            messages
          ),
          tree(messages)
        )
      )
    ).toEqual(["shown", "switched", "unloaded"]);
  });

  test("the server's list, then the files that packets publish after the load", () => {
    const saved = response(6, 6, [
      publishEnd([published("loaded", "/w/data.csv")]),
    ]);
    // The list also holds a background subagent's file, which no packet has.
    const loaded = load(
      [
        published("old-report", "/w/report.md", 1, "Report"),
        published("loaded", "/w/data.csv"),
        published("subagent", "/w/notes.md"),
      ],
      [saved]
    );
    // A live answer, with no saved ID yet, publishes the report's path again.
    const live = response(-1, undefined, [
      publishEnd([published("new-report", "/w/report.md", 2, "Report v2")]),
    ]);

    expect(
      chatPublishedFiles(loaded, tree([saved, live])).map(
        ({ file_id, title }) => [file_id, title]
      )
    ).toEqual([
      ["subagent", null],
      ["loaded", null],
      ["new-report", "Report v2"],
    ]);
  });

  test("a replayed file that the list leaves out stays out", () => {
    // The load leaves out the answer's own file, whose object is missing, a
    // file saved without an artifact, and an older version of the notes. It lists a
    // background subagent's version of the report.
    const saved = response(2, 2, [
      publishEnd([
        published("missing", "/w/report.md", 2),
        unversioned("pathless", "/w/pathless.md"),
        published("old-notes", "/w/notes.md", 1),
        published("notes", "/w/notes.md", 2),
      ]),
    ]);
    const loaded = load(
      [
        published("subagent", "/w/report.md", 1),
        published("notes", "/w/notes.md", 2),
      ],
      [saved]
    );

    expect(fileIds(chatPublishedFiles(loaded, tree([saved])))).toEqual([
      "notes",
      "subagent",
    ]);

    // An older page replays more of them; they stay out too.
    const older = response(1, 1, [
      publishEnd([unversioned("oldest", "/w/report.md")]),
    ]);
    const withOlder = addLoadedPublishedFiles(
      loaded,
      { published_files: null, packets: [older.packets] },
      2
    );
    expect(
      fileIds(chatPublishedFiles(withOlder, tree([older, saved])))
    ).toEqual(["notes", "subagent"]);

    // An answer saved after the load publishes a newer version, which keeps
    // the report's place.
    const newer = response(4, 4, [
      publishEnd([published("newer", "/w/report.md", 3)]),
    ]);
    expect(
      fileIds(chatPublishedFiles(withOlder, tree([older, saved, newer])))
    ).toEqual(["notes", "newer"]);
  });

  test("an answer that resumes after a load adds the files it publishes then", () => {
    // The answer waits for approval when the chat loads.
    const packets = [publishEnd([published("before", "/w/report.md")])];
    const answer = response(2, 2, packets);
    const loaded = load([published("before", "/w/report.md")], [answer]);

    // Approval resumes the same answer, with the same message ID.
    packets.push(publishEnd([published("after", "/w/report.md", 2)]));
    packets.push(publishEnd([published("chart", "/w/chart.png")]));

    expect(fileIds(chatPublishedFiles(loaded, tree([answer])))).toEqual([
      "chart",
      "after",
    ]);
  });

  test("a packet file that no load replayed shows only when newer than the listed version", () => {
    // A running answer publishes the report twice. A load whose list holds
    // the second version does not replay the answer.
    const answer = response(-1, undefined, [
      publishEnd([published("first", "/w/report.md", 1)]),
      publishEnd([published("second", "/w/report.md", 2)]),
    ]);
    const loaded = load([published("second", "/w/report.md", 2)], []);

    expect(fileIds(chatPublishedFiles(loaded, tree([answer])))).toEqual([
      "second",
    ]);

    answer.packets.push(publishEnd([published("third", "/w/report.md", 3)]));
    expect(fileIds(chatPublishedFiles(loaded, tree([answer])))).toEqual([
      "third",
    ]);
  });

  test("a shared chat shows its load's list, or its packets without one", () => {
    const answer = response(2, 2, [
      publishEnd([published("missing", "/w/report.md")]),
    ]);
    const shared = (session: Partial<BackendChatSession>) =>
      fileIds(
        chatPublishedFiles(
          addLoadedPublishedFiles(
            NO_LOADED_PUBLISHED_FILES,
            { packets: [answer.packets], ...session },
            1
          ),
          tree([answer])
        )
      );

    expect(
      shared({ published_files: [published("subagent", "/w/report.md", 2)] })
    ).toEqual(["subagent"]);
    expect(shared({})).toEqual(["missing"]);
  });
});

describe("addLoadedPublishedFiles", () => {
  const list = (fileId: string) => ({
    published_files: [published(fileId, "/w/report.md")],
    packets: [],
  });

  test("a load that started later replaces the list", () => {
    const first = addLoadedPublishedFiles(
      NO_LOADED_PUBLISHED_FILES,
      list("v1"),
      1
    );
    const second = addLoadedPublishedFiles(first, list("v2"), 2);
    expect(second.listed?.map((file) => file.file_id)).toEqual(["v2"]);
  });

  test("a load that started earlier but ends later keeps the newer list", () => {
    const newer = addLoadedPublishedFiles(
      NO_LOADED_PUBLISHED_FILES,
      list("v2"),
      2
    );
    const stale = addLoadedPublishedFiles(newer, list("v1"), 1);
    expect(stale.listed?.map((file) => file.file_id)).toEqual(["v2"]);
    expect(stale.listedBy).toBe(2);
  });
});

describe("newestVersion", () => {
  test("the newest version of the file's artifact that the files hold", () => {
    const v1 = published("a", "/w/report.md", 1);
    const v2 = published("b", "/w/report.md", 2);
    const other = published("c", "/w/chart.png", 5);

    expect(newestVersion(v1, [other, v2])).toBe(v2);
    expect(newestVersion(v2, [v1, other])).toBe(v2);
    // An equal version keeps the file itself
    expect(newestVersion(v2, [{ ...v2 }])).toBe(v2);
    expect(newestVersion(unversioned("d", "/w/report.md"), [v2]).file_id).toBe(
      "d"
    );
  });
});

describe("names", () => {
  test("a blank title shows the file name", () => {
    expect(
      publishedFileLabel({ ...published("a", "/w/report.md"), title: "  " })
    ).toBe("report.md");
    expect(
      publishedFileLabel({ ...published("a", "/w/report.md"), title: "Q3" })
    ).toBe("Q3");
  });

  test("files that share a shown name are the ones that show their path", () => {
    const files = [
      published("a", "/w/drafts/summary.csv"),
      published("b", "/w/final/summary.csv"),
      published("c", "/w/report.md"),
      published("d", "/w/other.md", 1, "summary.csv"),
    ];
    expect([...filesSharingALabel(files)]).toEqual(["a", "b", "d"]);
  });
});
