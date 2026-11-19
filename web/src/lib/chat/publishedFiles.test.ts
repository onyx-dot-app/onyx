import {
  type Packet,
  PacketType,
  type PublishedFile,
} from "@/app/app/services/streamingModels";
import type { ChatPublishedFile, Message } from "@/app/app/types";
import {
  branchPublishedFiles,
  filesSharingALabel,
  loadedPublishedFiles,
  publishedFileLabel,
} from "@/lib/chat/publishedFiles";

function published(
  fileId: string,
  path: string,
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
  };
}

function loaded(file: PublishedFile, messageId: number): ChatPublishedFile {
  return { ...file, message_id: messageId };
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

describe("branchPublishedFiles", () => {
  test("reads every publish_files result, nested calls included", () => {
    const packets = [
      publishEnd([published("a", "/w/report.md")]),
      publishEnd([published("b", "/w/chart.png")], 0),
    ];
    const answer = response(2, 2, packets);
    const fileIds = () =>
      branchPublishedFiles(null, tree([answer]), [answer]).all.map(
        (file) => file.file_id
      );

    expect(fileIds()).toEqual(["a", "b"]);

    // A stream appends to the same array.
    packets.push(publishEnd([published("c", "/w/notes.md")]));
    expect(fileIds()).toEqual(["a", "b", "c"]);
  });

  test("keeps the newest publish of each path, newest first", () => {
    const answer = response(2, 2, [
      publishEnd([
        published("a", "/w/report.md", "Draft"),
        published("b", "/w/chart.png"),
      ]),
      publishEnd([published("c", "/w/report.md")]),
      // A repeated report of one call adds nothing.
      publishEnd([published("c", "/w/report.md")]),
    ]);

    expect(
      branchPublishedFiles(null, tree([answer]), [answer]).latest.map(
        ({ file_id, title }) => [file_id, title]
      )
    ).toEqual([
      ["c", null],
      ["b", null],
    ]);
  });

  test("merges the load's list with live publishes by path", () => {
    // The load lists an older answer that is not loaded, and the loaded
    // answer, with a file of its background subagent that its packets lack.
    const branchFiles = {
      files: [
        loaded(published("old-report", "/w/report.md", "Report"), 2),
        loaded(published("old-chart", "/w/chart.png"), 2),
        loaded(published("loaded", "/w/data.csv"), 6),
        loaded(published("subagent", "/w/notes.md"), 6),
      ],
      throughMessageId: 6,
    };
    const saved = response(6, 6, [
      publishEnd([published("loaded", "/w/data.csv")]),
    ]);
    // A live answer, with no saved ID yet, publishes the report's path again.
    const live = response(-1, undefined, [
      publishEnd([published("new-report", "/w/report.md", "Report v2")]),
    ]);

    expect(
      branchPublishedFiles(branchFiles, tree([saved, live]), [
        saved,
        live,
      ]).latest.map(({ file_id, title }) => [file_id, title])
    ).toEqual([
      ["new-report", "Report v2"],
      ["subagent", null],
      ["loaded", null],
      ["old-chart", null],
    ]);
  });

  test("the load's list decides the files of the messages it knew of", () => {
    // The load leaves out the answer's own file, whose object is missing,
    // and lists its background subagent's file of the same path.
    const branchFiles = {
      files: [loaded(published("subagent", "/w/report.md"), 2)],
      throughMessageId: 2,
    };
    const saved = response(2, 2, [
      publishEnd([published("missing", "/w/report.md")]),
    ]);
    // An answer saved after the load publishes the path again.
    const newer = response(4, 4, [
      publishEnd([published("newer", "/w/report.md")]),
    ]);

    expect(
      branchPublishedFiles(branchFiles, tree([saved]), [saved]).all.map(
        ({ file_id }) => file_id
      )
    ).toEqual(["subagent"]);
    expect(
      branchPublishedFiles(branchFiles, tree([saved, newer]), [
        saved,
        newer,
      ]).latest.map(({ file_id }) => file_id)
    ).toEqual(["newer"]);
  });

  test("the shared view shows the load's list, or the packets without one", () => {
    const answer = response(2, 2, [
      publishEnd([published("missing", "/w/report.md")]),
    ]);
    const fileIds = (load: Parameters<typeof loadedPublishedFiles>[0]) =>
      branchPublishedFiles(loadedPublishedFiles(load), tree([answer]), [
        answer,
      ]).all.map(({ file_id }) => file_id);

    expect(
      fileIds({
        messages: [{ message_id: 1 }, { message_id: 2 }],
        published_files: [loaded(published("subagent", "/w/report.md"), 2)],
      })
    ).toEqual(["subagent"]);
    expect(
      fileIds({ messages: [{ message_id: 1 }, { message_id: 2 }] })
    ).toEqual(["missing"]);
  });

  test("leaves out the load's files of loaded messages off the branch", () => {
    // A branch switch: answer 6 is loaded but no longer on the branch.
    const branchFiles = {
      files: [loaded(published("switched", "/w/report.md"), 6)],
      throughMessageId: 7,
    };
    const hidden = response(6, 6, [
      publishEnd([published("switched", "/w/report.md")]),
    ]);
    const shown = response(7, 7, []);

    expect(
      branchPublishedFiles(branchFiles, tree([hidden, shown]), [shown]).latest
    ).toEqual([]);
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
      published("d", "/w/other.md", "summary.csv"),
    ];
    expect([...filesSharingALabel(files)]).toEqual(["a", "b", "d"]);
  });
});
