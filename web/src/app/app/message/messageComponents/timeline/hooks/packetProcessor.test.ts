/**
 * Unit tests for packetProcessor.ts
 *
 * Tests the pure packet processing functions that handle streaming packet parsing,
 * grouping, and state management. These tests serve as documentation for the
 * packet processing logic and prevent regressions.
 */
import {
  Packet,
  PacketType,
  StopReason,
} from "@/app/app/services/streamingModels";
import { createInitialState, processPackets } from "./packetProcessor";
import {
  createPacket,
  createStopPacket,
  createCitationPacket,
  createMessageStartPacket,
  createImageDeltaPacket,
  createSearchToolStartPacket,
  createSearchToolQueriesPacket,
  createSearchToolDocumentsPacket,
  createFetchToolStartPacket,
  createFetchToolUrlsPacket,
  createFetchToolDocumentsPacket,
  createPythonToolStartPacket,
  createPythonToolDeltaPacket,
} from "./__tests__/testHelpers";

// ============================================================================
// Tests
// ============================================================================

describe("packetProcessor", () => {
  describe("createInitialState", () => {
    test("creates state with correct nodeId", () => {
      const state = createInitialState(123);
      expect(state.nodeId).toBe(123);
    });

    test("initializes nextPacketIndex to 0", () => {
      const state = createInitialState(1);
      expect(state.nextPacketIndex).toBe(0);
    });

    test("initializes empty citations array", () => {
      const state = createInitialState(1);
      expect(state.citations).toEqual([]);
    });

    test("initializes empty seenCitationDocIds set", () => {
      const state = createInitialState(1);
      expect(state.seenCitationDocIds.size).toBe(0);
    });

    test("initializes empty citationMap", () => {
      const state = createInitialState(1);
      expect(state.citationMap).toEqual({});
    });

    test("initializes empty documentMap", () => {
      const state = createInitialState(1);
      expect(state.documentMap.size).toBe(0);
    });

    test("initializes empty groupedPacketsMap", () => {
      const state = createInitialState(1);
      expect(state.groupedPacketsMap.size).toBe(0);
    });

    test("initializes finalAnswerComing to false", () => {
      const state = createInitialState(1);
      expect(state.finalAnswerComing).toBe(false);
    });

    test("initializes stopPacketSeen to false", () => {
      const state = createInitialState(1);
      expect(state.stopPacketSeen).toBe(false);
    });

    test("initializes empty toolGroups array", () => {
      const state = createInitialState(1);
      expect(state.toolGroups).toEqual([]);
    });

    test("initializes empty potentialDisplayGroups array", () => {
      const state = createInitialState(1);
      expect(state.potentialDisplayGroups).toEqual([]);
    });
  });

  describe("processPackets - basic behavior", () => {
    test("processes only new packets on subsequent calls", () => {
      const state = createInitialState(1);

      // First call with 2 packets
      const packets1 = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
      ];
      const result1 = processPackets(state, packets1);
      expect(result1.nextPacketIndex).toBe(2);

      // Second call with 4 packets (2 new)
      const packets2 = [
        ...packets1,
        createMessageStartPacket({ turn_index: 1 }),
        createStopPacket(),
      ];
      const result2 = processPackets(result1, packets2);
      expect(result2.nextPacketIndex).toBe(4);
    });

    test("skips null packets", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        null as unknown as Packet,
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
      ];
      const result = processPackets(state, packets);

      // Should process valid packets without error
      expect(result.nextPacketIndex).toBe(3);
      expect(result.toolGroupKeys.has("0-0")).toBe(true);
    });

    test("skips undefined packets", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        undefined as unknown as Packet,
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
      ];
      const result = processPackets(state, packets);

      expect(result.nextPacketIndex).toBe(3);
      expect(result.toolGroupKeys.has("0-0")).toBe(true);
    });

    test("does not rebuild result arrays when no new packets", () => {
      const state = createInitialState(1);
      const packets = [createSearchToolStartPacket({ turn_index: 0 })];

      const result1 = processPackets(state, packets);
      const toolGroups1 = result1.toolGroups;

      // Process same packets again
      const result2 = processPackets(result1, packets);

      // Same reference since no new packets processed
      expect(result2.toolGroups).toBe(toolGroups1);
    });
  });

  describe("processPackets - stream reset detection", () => {
    test("resets state when packets array shrinks", () => {
      const state = createInitialState(1);

      // Process 5 packets
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createSearchToolQueriesPacket(["query1"], { turn_index: 0 }),
        createSearchToolDocumentsPacket([{ document_id: "doc-1" }], {
          turn_index: 0,
        }),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
        createMessageStartPacket({ turn_index: 1 }),
      ];
      const result1 = processPackets(state, packets);
      expect(result1.nextPacketIndex).toBe(5);
      expect(result1.documentMap.size).toBe(1);

      // Process with shorter array (simulating reset)
      const shorterPackets = [createSearchToolStartPacket({ turn_index: 0 })];
      const result2 = processPackets(result1, shorterPackets);

      // State should be reset
      expect(result2.nextPacketIndex).toBe(1);
      expect(result2.documentMap.size).toBe(0);
    });

    test("preserves nodeId after reset", () => {
      const state = createInitialState(42);

      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
      ];
      const result1 = processPackets(state, packets);

      // Shrink array to trigger reset
      const shorterPackets = [createSearchToolStartPacket({ turn_index: 0 })];
      const result2 = processPackets(result1, shorterPackets);

      expect(result2.nodeId).toBe(42);
    });
  });

  describe("packet grouping", () => {
    test("groups packets by turn_index-tab_index key", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0, tab_index: 0 }),
        createSearchToolQueriesPacket(["query"], {
          turn_index: 0,
          tab_index: 0,
        }),
        createPacket(PacketType.SECTION_END, { turn_index: 0, tab_index: 0 }),
      ];
      const result = processPackets(state, packets);

      expect(result.groupedPacketsMap.has("0-0")).toBe(true);
      expect(result.groupedPacketsMap.get("0-0")?.length).toBe(3);
    });

    test("separates packets with different turn_index", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
        createSearchToolStartPacket({ turn_index: 1 }),
        createPacket(PacketType.SECTION_END, { turn_index: 1 }),
      ];
      const result = processPackets(state, packets);

      expect(result.groupedPacketsMap.has("0-0")).toBe(true);
      expect(result.groupedPacketsMap.has("1-0")).toBe(true);
    });

    test("separates packets with different tab_index (parallel tools)", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0, tab_index: 0 }),
        createSearchToolStartPacket({ turn_index: 0, tab_index: 1 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0, tab_index: 0 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0, tab_index: 1 }),
      ];
      const result = processPackets(state, packets);

      expect(result.groupedPacketsMap.has("0-0")).toBe(true);
      expect(result.groupedPacketsMap.has("0-1")).toBe(true);
      expect(result.groupedPacketsMap.get("0-0")?.length).toBe(2);
      expect(result.groupedPacketsMap.get("0-1")?.length).toBe(2);
    });
  });

  describe("group categorization", () => {
    test("categorization happens only on first packet of group", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        // These delta packets should not affect categorization
        createSearchToolQueriesPacket(["query"], { turn_index: 0 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
      ];
      const result = processPackets(state, packets);

      expect(result.toolGroupKeys.has("0-0")).toBe(true);
      expect(result.toolGroupKeys.size).toBe(1);
    });

    test("classifies a tool when debug arrives before its start, including incremental updates", () => {
      const debug: Packet = {
        placement: { turn_index: 0 },
        obj: {
          type: PacketType.TOOL_CALL_DEBUG,
          tool_call_id: "call",
          tool_name: "lookup",
          tool_args: { query: "hello" },
        },
      };
      const start: Packet = {
        placement: { turn_index: 0 },
        obj: { type: PacketType.CUSTOM_TOOL_START, tool_name: "Lookup" },
      };
      const pending = processPackets(createInitialState(1), [debug]);
      expect(pending.toolGroupKeys.size).toBe(0);
      const result = processPackets(pending, [debug, start]);
      expect(result.toolGroupKeys.has("0-0")).toBe(true);
      expect(result.toolGroups[0]?.packets).toEqual([debug, start]);
    });

    test("classifies display content after control packets without changing mixed-group ownership", () => {
      const heartbeat: Packet = {
        placement: { turn_index: 0 },
        obj: { type: "chat_heartbeat" },
      };
      const result = processPackets(createInitialState(1), [
        heartbeat,
        createMessageStartPacket({ turn_index: 0 }),
        createSearchToolStartPacket({ turn_index: 0 }),
      ]);
      expect(result.displayGroupKeys.has("0-0")).toBe(true);
      expect(result.toolGroupKeys.size).toBe(0);
    });

    // Parameterized tests for tool packet types
    test.each([
      [PacketType.SEARCH_TOOL_START, "SEARCH_TOOL_START"],
      [PacketType.PYTHON_TOOL_START, "PYTHON_TOOL_START"],
      [PacketType.IMAGE_GENERATION_TOOL_START, "IMAGE_GENERATION_TOOL_START"],
      [PacketType.FETCH_TOOL_START, "FETCH_TOOL_START"],
      [PacketType.CUSTOM_TOOL_START, "CUSTOM_TOOL_START"],
      [PacketType.FILE_READER_START, "FILE_READER_START"],
      [PacketType.REASONING_START, "REASONING_START"],
      [PacketType.DEEP_RESEARCH_PLAN_START, "DEEP_RESEARCH_PLAN_START"],
      [PacketType.RESEARCH_AGENT_START, "RESEARCH_AGENT_START"],
    ])("%s categorizes as tool group", (packetType) => {
      const state = createInitialState(1);
      const packets = [createPacket(packetType, { turn_index: 0 })];
      const result = processPackets(state, packets);

      expect(result.toolGroupKeys.has("0-0")).toBe(true);
    });

    // Parameterized tests for display packet types
    test.each([[PacketType.MESSAGE_START, "MESSAGE_START"]])(
      "%s categorizes as display group",
      (packetType) => {
        const state = createInitialState(1);
        const packets = [createPacket(packetType, { turn_index: 0 })];
        const result = processPackets(state, packets);

        expect(result.displayGroupKeys.has("0-0")).toBe(true);
      }
    );
  });

  describe("SECTION_END and ERROR tracking", () => {
    test("tracks SECTION_END in groupKeysWithSectionEnd", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
      ];
      const result = processPackets(state, packets);

      expect(result.groupKeysWithSectionEnd.has("0-0")).toBe(true);
    });

    test("tracks ERROR as completion marker", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createPacket(
          PacketType.ERROR,
          { turn_index: 0 },
          { message: "Failed" }
        ),
      ];
      const result = processPackets(state, packets);

      expect(result.groupKeysWithSectionEnd.has("0-0")).toBe(true);
    });
  });

  describe("handleTurnTransition", () => {
    test("injects SECTION_END when turn_index changes", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        // No explicit SECTION_END before turn change
        createMessageStartPacket({ turn_index: 1 }),
      ];
      const result = processPackets(state, packets);

      // SECTION_END should be injected for turn 0
      expect(result.groupKeysWithSectionEnd.has("0-0")).toBe(true);
    });

    test("does not inject SECTION_END when only tab_index changes", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0, tab_index: 0 }),
        createSearchToolStartPacket({ turn_index: 0, tab_index: 1 }),
      ];
      const result = processPackets(state, packets);

      // No SECTION_END should be injected for parallel tools
      expect(result.groupKeysWithSectionEnd.has("0-0")).toBe(false);
      expect(result.groupKeysWithSectionEnd.has("0-1")).toBe(false);
    });

    test("does not inject duplicate SECTION_END", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
        createMessageStartPacket({ turn_index: 1 }),
      ];
      const result = processPackets(state, packets);

      const group = result.groupedPacketsMap.get("0-0");
      const sectionEndCount =
        group?.filter((p) => p.obj.type === PacketType.SECTION_END).length ?? 0;
      expect(sectionEndCount).toBe(1);
    });

    test("injects SECTION_END for all previous groups on turn change", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0, tab_index: 0 }),
        createSearchToolStartPacket({ turn_index: 0, tab_index: 1 }),
        // Turn changes
        createMessageStartPacket({ turn_index: 1 }),
      ];
      const result = processPackets(state, packets);

      expect(result.groupKeysWithSectionEnd.has("0-0")).toBe(true);
      expect(result.groupKeysWithSectionEnd.has("0-1")).toBe(true);
    });
  });

  describe("Search Tool flow", () => {
    test("SEARCH_TOOL_START categorizes group as tool", () => {
      const state = createInitialState(1);
      const packets = [createSearchToolStartPacket({ turn_index: 0 })];
      const result = processPackets(state, packets);

      expect(result.toolGroupKeys.has("0-0")).toBe(true);
    });

    test("SEARCH_TOOL_START with is_internet_search=true", () => {
      const state = createInitialState(1);
      const packets = [createSearchToolStartPacket({ turn_index: 0 }, true)];
      const result = processPackets(state, packets);

      const group = result.groupedPacketsMap.get("0-0");
      expect(
        (group![0]!.obj as { is_internet_search?: boolean }).is_internet_search
      ).toBe(true);
    });

    test("SEARCH_TOOL_START with is_internet_search=false", () => {
      const state = createInitialState(1);
      const packets = [createSearchToolStartPacket({ turn_index: 0 }, false)];
      const result = processPackets(state, packets);

      const group = result.groupedPacketsMap.get("0-0");
      expect(
        (group![0]!.obj as { is_internet_search?: boolean }).is_internet_search
      ).toBe(false);
    });

    test("SEARCH_TOOL_QUERIES_DELTA stores queries in packet", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createSearchToolQueriesPacket(["what is AI", "machine learning"], {
          turn_index: 0,
        }),
      ];
      const result = processPackets(state, packets);

      const group = result.groupedPacketsMap.get("0-0");
      expect((group![1]!.obj as { queries: string[] }).queries).toEqual([
        "what is AI",
        "machine learning",
      ]);
    });

    test("SEARCH_TOOL_DOCUMENTS_DELTA extracts documents to documentMap", () => {
      const state = createInitialState(1);
      const docs = [
        { document_id: "doc-1", semantic_identifier: "Doc 1" },
        { document_id: "doc-2", semantic_identifier: "Doc 2" },
      ];
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createSearchToolDocumentsPacket(docs, { turn_index: 0 }),
      ];
      const result = processPackets(state, packets);

      expect(result.documentMap.get("doc-1")).toBeDefined();
      expect(result.documentMap.get("doc-2")).toBeDefined();
    });

    test("full search flow: START -> QUERIES -> DOCUMENTS -> SECTION_END", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }, false),
        createSearchToolQueriesPacket(["test query"], { turn_index: 0 }),
        createSearchToolDocumentsPacket([{ document_id: "doc-1" }], {
          turn_index: 0,
        }),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
      ];
      const result = processPackets(state, packets);

      expect(result.toolGroups.length).toBe(1);
      expect(result.groupKeysWithSectionEnd.has("0-0")).toBe(true);
      expect(result.documentMap.has("doc-1")).toBe(true);
    });

    test("multiple QUERIES_DELTA packets accumulate", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createSearchToolQueriesPacket(["query 1"], { turn_index: 0 }),
        createSearchToolQueriesPacket(["query 2", "query 3"], {
          turn_index: 0,
        }),
      ];
      const result = processPackets(state, packets);

      const group = result.groupedPacketsMap.get("0-0");
      expect(group?.length).toBe(3);
    });

    test("multiple DOCUMENTS_DELTA packets accumulate documents", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createSearchToolDocumentsPacket([{ document_id: "doc-1" }], {
          turn_index: 0,
        }),
        createSearchToolDocumentsPacket([{ document_id: "doc-2" }], {
          turn_index: 0,
        }),
      ];
      const result = processPackets(state, packets);

      expect(result.documentMap.has("doc-1")).toBe(true);
      expect(result.documentMap.has("doc-2")).toBe(true);
    });

    test("SEARCH_TOOL_START resets finalAnswerComing if after message", () => {
      const state = createInitialState(1);
      const packets = [
        createMessageStartPacket({ turn_index: 0 }),
        // Tool comes after message (Claude workaround)
        createSearchToolStartPacket({ turn_index: 1 }),
      ];
      const result = processPackets(state, packets);

      // finalAnswerComing should be reset since tool follows message
      expect(result.finalAnswerComing).toBe(false);
    });

    test("parallel search tools at same turn_index with different tab_index", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0, tab_index: 0 }),
        createSearchToolStartPacket({ turn_index: 0, tab_index: 1 }),
        createSearchToolDocumentsPacket([{ document_id: "doc-a" }], {
          turn_index: 0,
          tab_index: 0,
        }),
        createSearchToolDocumentsPacket([{ document_id: "doc-b" }], {
          turn_index: 0,
          tab_index: 1,
        }),
      ];
      const result = processPackets(state, packets);

      expect(result.toolGroups.length).toBe(2);
      expect(result.documentMap.has("doc-a")).toBe(true);
      expect(result.documentMap.has("doc-b")).toBe(true);
    });
  });

  describe("Fetch Tool flow", () => {
    test("FETCH_TOOL_START categorizes group as tool", () => {
      const state = createInitialState(1);
      const packets = [createFetchToolStartPacket({ turn_index: 0 })];
      const result = processPackets(state, packets);

      expect(result.toolGroupKeys.has("0-0")).toBe(true);
    });

    test("FETCH_TOOL_URLS stores urls in packet", () => {
      const state = createInitialState(1);
      const packets = [
        createFetchToolStartPacket({ turn_index: 0 }),
        createFetchToolUrlsPacket(["https://example.com", "https://test.com"], {
          turn_index: 0,
        }),
      ];
      const result = processPackets(state, packets);

      const group = result.groupedPacketsMap.get("0-0");
      expect((group![1]!.obj as { urls: string[] }).urls).toEqual([
        "https://example.com",
        "https://test.com",
      ]);
    });

    test("FETCH_TOOL_DOCUMENTS extracts documents to documentMap", () => {
      const state = createInitialState(1);
      const packets = [
        createFetchToolStartPacket({ turn_index: 0 }),
        createFetchToolDocumentsPacket([{ document_id: "fetched-doc-1" }], {
          turn_index: 0,
        }),
      ];
      const result = processPackets(state, packets);

      expect(result.documentMap.has("fetched-doc-1")).toBe(true);
    });

    test("full fetch flow: START -> URLS -> DOCUMENTS -> SECTION_END", () => {
      const state = createInitialState(1);
      const packets = [
        createFetchToolStartPacket({ turn_index: 0 }),
        createFetchToolUrlsPacket(["https://example.com"], { turn_index: 0 }),
        createFetchToolDocumentsPacket([{ document_id: "url-doc" }], {
          turn_index: 0,
        }),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
      ];
      const result = processPackets(state, packets);

      expect(result.toolGroups.length).toBe(1);
      expect(result.groupKeysWithSectionEnd.has("0-0")).toBe(true);
    });

    test("multiple URLs in single FETCH_TOOL_URLS packet", () => {
      const state = createInitialState(1);
      const packets = [
        createFetchToolStartPacket({ turn_index: 0 }),
        createFetchToolUrlsPacket(
          ["https://a.com", "https://b.com", "https://c.com"],
          { turn_index: 0 }
        ),
      ];
      const result = processPackets(state, packets);

      const group = result.groupedPacketsMap.get("0-0");
      expect((group![1]!.obj as { urls: string[] }).urls.length).toBe(3);
    });

    test("empty urls array handling", () => {
      const state = createInitialState(1);
      const packets = [
        createFetchToolStartPacket({ turn_index: 0 }),
        createFetchToolUrlsPacket([], { turn_index: 0 }),
      ];
      const result = processPackets(state, packets);

      const group = result.groupedPacketsMap.get("0-0");
      expect((group![1]!.obj as { urls: string[] }).urls).toEqual([]);
    });

    test("FETCH_TOOL_START resets finalAnswerComing if after message", () => {
      const state = createInitialState(1);
      const packets = [
        createMessageStartPacket({ turn_index: 0 }),
        createFetchToolStartPacket({ turn_index: 1 }),
      ];
      const result = processPackets(state, packets);

      expect(result.finalAnswerComing).toBe(false);
    });

    test("fetch tool with ERROR instead of SECTION_END", () => {
      const state = createInitialState(1);
      const packets = [
        createFetchToolStartPacket({ turn_index: 0 }),
        createFetchToolUrlsPacket(["https://invalid.com"], { turn_index: 0 }),
        createPacket(
          PacketType.ERROR,
          { turn_index: 0 },
          { error: "Failed to fetch" }
        ),
      ];
      const result = processPackets(state, packets);

      // ERROR counts as section end
      expect(result.groupKeysWithSectionEnd.has("0-0")).toBe(true);
    });
  });

  describe("Python Tool flow", () => {
    test("PYTHON_TOOL_START categorizes group as tool", () => {
      const state = createInitialState(1);
      const packets = [
        createPythonToolStartPacket("print('hello')", { turn_index: 0 }),
      ];
      const result = processPackets(state, packets);

      expect(result.toolGroupKeys.has("0-0")).toBe(true);
    });

    test("PYTHON_TOOL_START stores code in packet", () => {
      const state = createInitialState(1);
      const code = "import pandas as pd\ndf = pd.read_csv('data.csv')";
      const packets = [createPythonToolStartPacket(code, { turn_index: 0 })];
      const result = processPackets(state, packets);

      const group = result.groupedPacketsMap.get("0-0");
      expect((group![0]!.obj as { code: string }).code).toBe(code);
    });

    test("PYTHON_TOOL_DELTA stores stdout/stderr/file_ids", () => {
      const state = createInitialState(1);
      const packets = [
        createPythonToolStartPacket("print('test')", { turn_index: 0 }),
        createPythonToolDeltaPacket("test\n", "", [], { turn_index: 0 }),
      ];
      const result = processPackets(state, packets);

      const group = result.groupedPacketsMap.get("0-0");
      const delta = group![1]!.obj as {
        stdout: string;
        stderr: string;
        file_ids: string[];
      };
      expect(delta.stdout).toBe("test\n");
      expect(delta.stderr).toBe("");
    });

    test("PYTHON_TOOL_DELTA with file_ids (generated files)", () => {
      const state = createInitialState(1);
      const packets = [
        createPythonToolStartPacket("plt.savefig('chart.png')", {
          turn_index: 0,
        }),
        createPythonToolDeltaPacket("", "", ["file-123", "file-456"], {
          turn_index: 0,
        }),
      ];
      const result = processPackets(state, packets);

      const group = result.groupedPacketsMap.get("0-0");
      expect((group![1]!.obj as { file_ids: string[] }).file_ids).toEqual([
        "file-123",
        "file-456",
      ]);
    });

    test("multiple DELTA packets (streaming output)", () => {
      const state = createInitialState(1);
      const packets = [
        createPythonToolStartPacket("for i in range(3): print(i)", {
          turn_index: 0,
        }),
        createPythonToolDeltaPacket("0\n", "", [], { turn_index: 0 }),
        createPythonToolDeltaPacket("1\n", "", [], { turn_index: 0 }),
        createPythonToolDeltaPacket("2\n", "", [], { turn_index: 0 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
      ];
      const result = processPackets(state, packets);

      const group = result.groupedPacketsMap.get("0-0");
      expect(group?.length).toBe(5); // START + 3 DELTAs + SECTION_END
    });

    test("python tool with stderr (error output)", () => {
      const state = createInitialState(1);
      const packets = [
        createPythonToolStartPacket("undefined_var", { turn_index: 0 }),
        createPythonToolDeltaPacket(
          "",
          "NameError: name 'undefined_var' is not defined",
          [],
          { turn_index: 0 }
        ),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
      ];
      const result = processPackets(state, packets);

      const group = result.groupedPacketsMap.get("0-0");
      expect((group![1]!.obj as { stderr: string }).stderr).toContain(
        "NameError"
      );
    });

    test("PYTHON_TOOL_START resets finalAnswerComing if after message", () => {
      const state = createInitialState(1);
      const packets = [
        createMessageStartPacket({ turn_index: 0 }),
        createPythonToolStartPacket("print(1)", { turn_index: 1 }),
      ];
      const result = processPackets(state, packets);

      expect(result.finalAnswerComing).toBe(false);
    });

    test("python tool with ERROR instead of SECTION_END", () => {
      const state = createInitialState(1);
      const packets = [
        createPythonToolStartPacket("crash()", { turn_index: 0 }),
        createPacket(
          PacketType.ERROR,
          { turn_index: 0 },
          { message: "Execution failed" }
        ),
      ];
      const result = processPackets(state, packets);

      expect(result.groupKeysWithSectionEnd.has("0-0")).toBe(true);
    });
  });

  describe("handleStreamingStatusPacket", () => {
    test("sets finalAnswerComing on MESSAGE_START", () => {
      const state = createInitialState(1);
      const packets = [createMessageStartPacket({ turn_index: 0 })];
      const result = processPackets(state, packets);

      expect(result.finalAnswerComing).toBe(true);
    });

    test("sets finalAnswerComing on MESSAGE_DELTA", () => {
      const state = createInitialState(1);
      const packets = [
        createMessageStartPacket({ turn_index: 0 }),
        createPacket(
          PacketType.MESSAGE_DELTA,
          { turn_index: 0 },
          { content: "Hello" }
        ),
      ];
      const result = processPackets(state, packets);

      expect(result.finalAnswerComing).toBe(true);
    });

    test("does not start the answer on IMAGE_GENERATION_TOOL_START", () => {
      const state = createInitialState(1);
      const packets = [
        createPacket(PacketType.IMAGE_GENERATION_TOOL_START, { turn_index: 0 }),
      ];
      const result = processPackets(state, packets);

      expect(result.finalAnswerComing).toBe(false);
    });

    test("captures toolProcessingDuration from MESSAGE_START", () => {
      const state = createInitialState(1);
      const packets = [createMessageStartPacket({ turn_index: 0 }, 2.5)];
      const result = processPackets(state, packets);

      expect(result.toolProcessingDuration).toBe(2.5);
    });
  });

  describe("handleStopPacket", () => {
    test("sets stopPacketSeen to true", () => {
      const state = createInitialState(1);
      const packets = [createStopPacket()];
      const result = processPackets(state, packets);

      expect(result.stopPacketSeen).toBe(true);
    });

    test("stores stop reason", () => {
      const state = createInitialState(1);
      const packets = [createStopPacket(StopReason.FINISHED)];
      const result = processPackets(state, packets);

      expect(result.stopReason).toBe(StopReason.FINISHED);
    });

    test("injects SECTION_END for all incomplete groups", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        // No explicit SECTION_END
        createStopPacket(),
      ];
      const result = processPackets(state, packets);

      expect(result.groupKeysWithSectionEnd.has("0-0")).toBe(true);
    });

    test("does not process duplicate STOP packets", () => {
      const state = createInitialState(1);
      const packets = [
        createStopPacket(StopReason.FINISHED),
        createStopPacket(StopReason.USER_CANCELLED),
      ];
      const result = processPackets(state, packets);

      // First stop reason should be preserved
      expect(result.stopReason).toBe(StopReason.FINISHED);
    });

    test("ends each open nested call, which gets no packets after Stop", () => {
      const nested = { turn_index: 0, sub_turn_index: 0 };
      const result = processPackets(createInitialState(1), [
        createPacket(
          PacketType.CODE_MODE_START,
          { turn_index: 0 },
          { code: "" }
        ),
        createPacket(PacketType.CUSTOM_TOOL_START, nested, {
          tool_name: "lookup",
        }),
        createStopPacket(StopReason.USER_CANCELLED),
      ]);

      expect(result.toolGroups[0]!.nestedCalls[0]!.complete).toBe(true);
    });
  });

  describe("handleToolAfterMessagePacket", () => {
    test("resets finalAnswerComing when actual tool follows message", () => {
      const state = createInitialState(1);
      const packets = [
        createMessageStartPacket({ turn_index: 0 }),
        createSearchToolStartPacket({ turn_index: 1 }),
      ];
      const result = processPackets(state, packets);

      expect(result.finalAnswerComing).toBe(false);
    });

    test("a tool's debug packet waits for its start to reset finalAnswerComing", () => {
      const packets = [
        createMessageStartPacket({ turn_index: 0 }),
        createPacket(
          PacketType.TOOL_CALL_DEBUG,
          { turn_index: 1 },
          { tool_call_id: "call-1", tool_name: "search", tool_args: {} }
        ),
      ];
      const afterDebug = processPackets(createInitialState(1), packets);
      expect(afterDebug.finalAnswerComing).toBe(true);

      const afterStart = processPackets(afterDebug, [
        ...packets,
        createSearchToolStartPacket({ turn_index: 1 }),
      ]);
      expect(afterStart.finalAnswerComing).toBe(false);
    });

    test("REASONING_START does NOT reset finalAnswerComing (critical fix)", () => {
      const state = createInitialState(1);
      const packets = [
        createMessageStartPacket({ turn_index: 0 }),
        createPacket(PacketType.REASONING_START, { turn_index: 1 }),
      ];
      const result = processPackets(state, packets);

      // Reasoning is just thinking, not an actual tool call
      expect(result.finalAnswerComing).toBe(true);
    });

    test("REASONING_DELTA does NOT reset finalAnswerComing", () => {
      const state = createInitialState(1);
      const packets = [
        createMessageStartPacket({ turn_index: 0 }),
        createPacket(
          PacketType.REASONING_DELTA,
          { turn_index: 1 },
          { reasoning: "thinking..." }
        ),
      ];
      const result = processPackets(state, packets);

      expect(result.finalAnswerComing).toBe(true);
    });

    test("does not reset finalAnswerComing if stopPacketSeen", () => {
      const state = createInitialState(1);
      const packets = [
        createMessageStartPacket({ turn_index: 0 }),
        createStopPacket(),
        createSearchToolStartPacket({ turn_index: 1 }),
      ];
      const result = processPackets(state, packets);

      // Stop already seen, so finalAnswerComing should remain true
      expect(result.finalAnswerComing).toBe(true);
    });

    test("a tool whose arguments streamed before the message resets it when it starts", () => {
      const state = createInitialState(1);
      const packets = [
        createPacket(
          PacketType.TOOL_CALL_ARGUMENT_DELTA,
          { turn_index: 0 },
          { tool_type: "python", argument_deltas: { code: "print(1)" } }
        ),
        createMessageStartPacket({ turn_index: 1 }),
      ];
      expect(processPackets(state, packets).finalAnswerComing).toBe(true);

      const result = processPackets(state, [
        ...packets,
        createPythonToolStartPacket("print(1)", { turn_index: 0 }),
      ]);
      expect(result.finalAnswerComing).toBe(false);
    });
  });

  describe("image generation counting", () => {
    test("categorizes image generation as a tool step", () => {
      const state = createInitialState(1);
      const packets = [
        createPacket(PacketType.IMAGE_GENERATION_TOOL_START, { turn_index: 0 }),
      ];
      const result = processPackets(state, packets);
      expect(result.toolGroupKeys.has("0-0")).toBe(true);
    });

    test("counts images from IMAGE_GENERATION_TOOL_DELTA", () => {
      const state = createInitialState(1);
      const packets = [
        createPacket(PacketType.IMAGE_GENERATION_TOOL_START, { turn_index: 0 }),
        createImageDeltaPacket(2, { turn_index: 0 }),
      ];
      const result = processPackets(state, packets);

      expect(result.generatedImages.length).toBe(2);
    });

    test("collects images from nested image calls", () => {
      const state = createInitialState(1);
      const packets = [
        createPacket(PacketType.IMAGE_GENERATION_TOOL_START, { turn_index: 0 }),
        createImageDeltaPacket(2, { turn_index: 0 }, "top"),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
        createPacket(
          PacketType.CODE_MODE_START,
          { turn_index: 1 },
          {
            code: "await generate_image(prompt='x')",
          }
        ),
        createPacket(PacketType.IMAGE_GENERATION_TOOL_START, {
          turn_index: 1,
          sub_turn_index: 0,
        }),
        createImageDeltaPacket(
          1,
          { turn_index: 1, sub_turn_index: 0 },
          "nested"
        ),
      ];
      const result = processPackets(state, packets);

      expect(result.generatedImages.map((i) => i.file_id)).toEqual([
        "top-0",
        "top-1",
        "nested-0",
      ]);
    });

    test("deduplicates images from repeated DELTA packets", () => {
      const state = createInitialState(1);
      const packets = [
        createPacket(PacketType.IMAGE_GENERATION_TOOL_START, { turn_index: 0 }),
        createImageDeltaPacket(1, { turn_index: 0 }),
        createImageDeltaPacket(2, { turn_index: 0 }),
        createImageDeltaPacket(1, { turn_index: 0 }),
      ];
      const result = processPackets(state, packets);

      expect(result.generatedImages.length).toBe(2);
    });
  });

  describe("buildGroupsFromKeys", () => {
    test("filters out groups without content packets", () => {
      const state = createInitialState(1);
      // Create a group with only SECTION_END (no content packet)
      const packets = [createPacket(PacketType.SECTION_END, { turn_index: 0 })];
      const result = processPackets(state, packets);

      // Group should exist in map but not in result arrays
      expect(result.groupedPacketsMap.has("0-0")).toBe(true);
      expect(result.toolGroups.length).toBe(0);
      expect(result.potentialDisplayGroups.length).toBe(0);
    });

    test("sorts groups by turn_index then tab_index", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 1, tab_index: 1 }),
        createSearchToolStartPacket({ turn_index: 0, tab_index: 0 }),
        createSearchToolStartPacket({ turn_index: 1, tab_index: 0 }),
        createSearchToolStartPacket({ turn_index: 0, tab_index: 1 }),
      ];
      const result = processPackets(state, packets);

      const keys = result.toolGroups.map(
        (g) => `${g.turn_index}-${g.tab_index}`
      );
      expect(keys).toEqual(["0-0", "0-1", "1-0", "1-1"]);
    });

    test("creates new packet array references (immutability)", () => {
      const state = createInitialState(1);
      const packets = [createSearchToolStartPacket({ turn_index: 0 })];
      const result = processPackets(state, packets);

      const mapPackets = result.groupedPacketsMap.get("0-0");
      const resultPackets = result.toolGroups[0]?.packets;

      // Should be different array references
      expect(resultPackets).not.toBe(mapPackets);
      // But same content
      expect(resultPackets).toEqual(mapPackets);
    });

    test("includes groups with MESSAGE_START as content", () => {
      const state = createInitialState(1);
      const packets = [createMessageStartPacket({ turn_index: 0 })];
      const result = processPackets(state, packets);

      expect(result.potentialDisplayGroups.length).toBe(1);
    });

    test("includes groups with SEARCH_TOOL_START as content", () => {
      const state = createInitialState(1);
      const packets = [createSearchToolStartPacket({ turn_index: 0 })];
      const result = processPackets(state, packets);

      expect(result.toolGroups.length).toBe(1);
    });
  });

  describe("multi-tool scenarios", () => {
    test("Search + Python + Fetch in same conversation", () => {
      const state = createInitialState(1);
      const packets = [
        // Turn 0: Search
        createSearchToolStartPacket({ turn_index: 0, tab_index: 0 }),
        createSearchToolDocumentsPacket([{ document_id: "search-doc" }], {
          turn_index: 0,
          tab_index: 0,
        }),
        createPacket(PacketType.SECTION_END, { turn_index: 0, tab_index: 0 }),

        // Turn 1: Python
        createPythonToolStartPacket("analyze()", {
          turn_index: 1,
          tab_index: 0,
        }),
        createPythonToolDeltaPacket("Result: 42", "", [], {
          turn_index: 1,
          tab_index: 0,
        }),
        createPacket(PacketType.SECTION_END, { turn_index: 1, tab_index: 0 }),

        // Turn 2: Fetch
        createFetchToolStartPacket({ turn_index: 2, tab_index: 0 }),
        createFetchToolUrlsPacket(["https://api.example.com"], {
          turn_index: 2,
          tab_index: 0,
        }),
        createFetchToolDocumentsPacket([{ document_id: "fetch-doc" }], {
          turn_index: 2,
          tab_index: 0,
        }),
        createPacket(PacketType.SECTION_END, { turn_index: 2, tab_index: 0 }),

        // Turn 3: Final answer
        createMessageStartPacket({ turn_index: 3, tab_index: 0 }),
        createStopPacket(),
      ];
      const result = processPackets(state, packets);

      expect(result.toolGroups.length).toBe(3);
      expect(result.potentialDisplayGroups.length).toBe(1);
      expect(result.documentMap.has("search-doc")).toBe(true);
      expect(result.documentMap.has("fetch-doc")).toBe(true);
      expect(result.finalAnswerComing).toBe(true);
      expect(result.stopPacketSeen).toBe(true);
    });

    test("parallel search tools then message", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0, tab_index: 0 }),
        createSearchToolStartPacket({ turn_index: 0, tab_index: 1 }),
        createSearchToolStartPacket({ turn_index: 0, tab_index: 2 }),
        createSearchToolDocumentsPacket([{ document_id: "doc-0" }], {
          turn_index: 0,
          tab_index: 0,
        }),
        createSearchToolDocumentsPacket([{ document_id: "doc-1" }], {
          turn_index: 0,
          tab_index: 1,
        }),
        createSearchToolDocumentsPacket([{ document_id: "doc-2" }], {
          turn_index: 0,
          tab_index: 2,
        }),
        createPacket(PacketType.SECTION_END, { turn_index: 0, tab_index: 0 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0, tab_index: 1 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0, tab_index: 2 }),
        createMessageStartPacket({ turn_index: 1 }),
        createStopPacket(),
      ];
      const result = processPackets(state, packets);

      expect(result.toolGroups.length).toBe(3);
      expect(result.documentMap.size).toBe(3);
      expect(result.finalAnswerComing).toBe(true);
    });

    test("tool-after-message Claude workaround scenario", () => {
      const state = createInitialState(1);
      const packets = [
        // Claude sends message first
        createMessageStartPacket({ turn_index: 0 }),
        createPacket(
          PacketType.MESSAGE_DELTA,
          { turn_index: 0 },
          { content: "Let me search for that..." }
        ),
        // Then tool is called (this is the workaround case)
        createSearchToolStartPacket({ turn_index: 1 }),
        createSearchToolDocumentsPacket([{ document_id: "doc-1" }], {
          turn_index: 1,
        }),
        createPacket(PacketType.SECTION_END, { turn_index: 1 }),
        // Then actual final answer
        createMessageStartPacket({ turn_index: 2 }),
        createStopPacket(),
      ];
      const result = processPackets(state, packets);

      expect(result.toolGroups.length).toBe(1);
      expect(result.potentialDisplayGroups.length).toBe(2);
      expect(result.finalAnswerComing).toBe(true);
    });

    test("image generation flow", () => {
      const state = createInitialState(1);
      const packets = [
        createPacket(PacketType.IMAGE_GENERATION_TOOL_START, { turn_index: 0 }),
        createImageDeltaPacket(1, { turn_index: 0 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
        createStopPacket(),
      ];
      const result = processPackets(state, packets);

      expect(result.generatedImages.length).toBe(1);
      expect(result.finalAnswerComing).toBe(false);
      expect(result.toolGroupKeys.has("0-0")).toBe(true);
    });

    test("deep research with sub-agents", () => {
      const state = createInitialState(1);
      const packets = [
        createPacket(PacketType.DEEP_RESEARCH_PLAN_START, { turn_index: 0 }),
        createPacket(
          PacketType.DEEP_RESEARCH_PLAN_DELTA,
          { turn_index: 0 },
          { content: "Plan..." }
        ),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
        createPacket(
          PacketType.RESEARCH_AGENT_START,
          { turn_index: 1 },
          { research_task: "Research topic A" }
        ),
        createSearchToolStartPacket({ turn_index: 1, sub_turn_index: 0 }),
        createPacket(PacketType.SECTION_END, {
          turn_index: 1,
          sub_turn_index: 0,
        }),
        createPacket(PacketType.SECTION_END, { turn_index: 1 }),
        createMessageStartPacket({ turn_index: 2 }),
        createStopPacket(),
      ];
      const result = processPackets(state, packets);

      expect(result.toolGroups.length).toBe(2); // Plan + Research agent
      expect(result.potentialDisplayGroups.length).toBe(1);
    });
  });

  describe("edge cases", () => {
    test("handles empty packets array", () => {
      const state = createInitialState(1);
      const result = processPackets(state, []);

      expect(result.nextPacketIndex).toBe(0);
      expect(result.toolGroups).toEqual([]);
    });

    test("handles sparse packets array", () => {
      const state = createInitialState(1);
      const packets: Packet[] = [];
      packets[0] = createSearchToolStartPacket({ turn_index: 0 });
      packets[5] = createPacket(PacketType.SECTION_END, { turn_index: 0 });

      const result = processPackets(state, packets);

      // Should handle sparse array
      expect(result.nextPacketIndex).toBe(6);
    });

    test("handles large turn indices", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 9999 }),
        createPacket(PacketType.SECTION_END, { turn_index: 9999 }),
      ];
      const result = processPackets(state, packets);

      expect(result.toolGroupKeys.has("9999-0")).toBe(true);
    });

    test("handles large tab indices", () => {
      const state = createInitialState(1);
      const packets = [
        createSearchToolStartPacket({ turn_index: 0, tab_index: 999 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0, tab_index: 999 }),
      ];
      const result = processPackets(state, packets);

      expect(result.toolGroupKeys.has("0-999")).toBe(true);
    });
  });

  describe("code mode", () => {
    const parent = { turn_index: 1, tab_index: 0 };
    const nested = { ...parent, sub_turn_index: 0 };

    function codeModeStart(): Packet[] {
      return [
        createPacket(PacketType.TOOL_CALL_ARGUMENT_DELTA, parent, {
          tool_type: "execute_code",
          tool_id: "call-1",
          argument_deltas: { code: "print(1)" },
        }),
        createPacket(PacketType.CODE_MODE_START, parent, { code: "print(1)" }),
      ];
    }

    test("a group with only the streamed program is a tool step", () => {
      const state = createInitialState(1);
      const result = processPackets(state, codeModeStart().slice(0, 1));

      expect(result.toolGroups.length).toBe(1);
    });

    test("nested calls join the code mode group", () => {
      const state = createInitialState(1);
      const result = processPackets(state, [
        ...codeModeStart(),
        createSearchToolStartPacket(nested),
        createPacket(PacketType.SECTION_END, nested),
      ]);

      expect(result.toolGroups.length).toBe(1);
      expect(result.toolGroups[0]?.packets.length).toBe(2);
      expect(result.toolGroups[0]?.streamPackets.length).toBe(4);
      expect(result.toolGroups[0]?.nestedCalls).toHaveLength(1);
    });

    test("nested search documents feed the document map", () => {
      const state = createInitialState(1);
      const result = processPackets(state, [
        ...codeModeStart(),
        createSearchToolStartPacket(nested),
        createSearchToolDocumentsPacket(
          [{ document_id: "doc-1", semantic_identifier: "Doc 1" }],
          nested
        ),
        createFetchToolDocumentsPacket([{ document_id: "doc-2" }], {
          ...parent,
          sub_turn_index: 1,
        }),
      ]);

      expect(result.documentMap.has("doc-1")).toBe(true);
      expect(result.documentMap.has("doc-2")).toBe(true);
    });

    test("a nested image generation start is not the final answer", () => {
      const state = createInitialState(1);
      const result = processPackets(state, [
        ...codeModeStart(),
        createPacket(PacketType.IMAGE_GENERATION_TOOL_START, nested),
      ]);

      expect(result.finalAnswerComing).toBe(false);
      expect(result.displayGroupKeys.size).toBe(0);
    });

    describe("cells", () => {
      const waitObservation = { turn_index: 2, tab_index: 0 };
      const answer = { turn_index: 3, tab_index: 0 };

      function runningObservation(): Packet[] {
        return [
          createPacket(PacketType.CODE_MODE_START, parent, {
            code: "print(1)",
            cell_id: null,
            observation: 0,
          }),
          createPacket(PacketType.CODE_MODE_DELTA, parent, {
            stdout: "1\n",
            status: "running",
            cell_id: 1,
            observation: 0,
          }),
          createPacket(PacketType.SECTION_END, parent),
        ];
      }

      function closingRecord(): Packet[] {
        return [
          createPacket(PacketType.IMAGE_GENERATION_TOOL_START, nested),
          createImageDeltaPacket(1, nested, "closing"),
          createPacket(PacketType.SECTION_END, nested),
          createPacket(PacketType.CODE_MODE_DELTA, parent, { stdout: "2\n" }),
          createPacket(PacketType.CODE_MODE_DELTA, parent, {
            status: "terminated",
            tool_call_count: 1,
            response_ended: true,
          }),
        ];
      }

      test("each observation of a cell is its own step", () => {
        const result = processPackets(createInitialState(1), [
          ...runningObservation(),
          createPacket(PacketType.CODE_MODE_START, waitObservation, {
            code: "",
            cell_id: 1,
            observation: 1,
          }),
          createPacket(PacketType.CODE_MODE_DELTA, waitObservation, {
            stdout: "2\n",
            status: "completed",
            cell_id: 1,
            observation: 1,
          }),
          createPacket(PacketType.SECTION_END, waitObservation),
        ]);

        expect(
          result.toolGroups.map((g) => [g.turn_index, g.tab_index])
        ).toEqual([
          [1, 0],
          [2, 0],
        ]);
        expect(result.groupKeysWithSectionEnd.has("1-0")).toBe(true);
        expect(result.groupKeysWithSectionEnd.has("2-0")).toBe(true);
      });

      test("a closing record after the answer joins its observation", () => {
        const result = processPackets(createInitialState(1), [
          ...runningObservation(),
          createMessageStartPacket(answer),
          createPacket(PacketType.MESSAGE_DELTA, answer, { content: "Done." }),
          ...closingRecord(),
        ]);

        expect(result.toolGroups.length).toBe(1);
        expect(result.toolGroups[0]?.packets.at(-1)?.obj).toMatchObject({
          type: PacketType.CODE_MODE_DELTA,
          response_ended: true,
        });
        // A late packet of a known step is not a new tool call.
        expect(result.finalAnswerComing).toBe(true);
        expect(result.generatedImages.map((i) => i.file_id)).toEqual([
          "closing-0",
        ]);
      });

      test("a replayed response gives the same steps as the live one", () => {
        // The closing record follows the step's SECTION_END in both. Live, it
        // also follows the streamed answer; replay sends it before the answer.
        const live = processPackets(createInitialState(1), [
          ...runningObservation(),
          createMessageStartPacket(answer),
          createPacket(PacketType.MESSAGE_DELTA, answer, { content: "Done." }),
          ...closingRecord(),
          createStopPacket(),
        ]);
        const replay = processPackets(createInitialState(2), [
          ...runningObservation(),
          ...closingRecord(),
          createPacket(PacketType.MESSAGE_START, answer, {
            id: "msg-1",
            content: "Done.",
            final_documents: null,
          }),
          createPacket(PacketType.SECTION_END, answer),
          createStopPacket(),
        ]);

        expect(replay.toolGroups).toEqual(live.toolGroups);
        expect(replay.groupKeysWithSectionEnd).toEqual(
          live.groupKeysWithSectionEnd
        );
        expect(replay.generatedImages).toEqual(live.generatedImages);
        expect(live.finalAnswerComing).toBe(true);
        expect(replay.finalAnswerComing).toBe(true);
      });
    });
  });
});

describe("nested packet ownership", () => {
  const parents = [
    ["research agent", PacketType.RESEARCH_AGENT_START, { research_task: "R" }],
    ["code mode", PacketType.CODE_MODE_START, { code: "" }],
    ["coding agent", PacketType.CODING_AGENT_START, { query: "q", repo: "r" }],
  ] as const;
  test.each(
    parents.flatMap(([name, type, fields]) =>
      [PacketType.SECTION_END, PacketType.ERROR].map(
        (endType) => [name, endType, type, fields] as const
      )
    )
  )(
    "%s: nested %s leaves the parent open until next turn or Stop",
    (_name, endType, parentType, parentFields) => {
      for (const closing of [
        createMessageStartPacket({ turn_index: 1 }),
        createStopPacket(),
      ]) {
        const nested = { turn_index: 0, sub_turn_index: 0 };
        const packets = [
          createPacket(parentType, { turn_index: 0 }, parentFields),
          createSearchToolStartPacket(nested),
          createPacket(endType, nested),
          createMessageStartPacket({ turn_index: 0, sub_turn_index: 1 }, 99),
          createPacket(
            PacketType.MESSAGE_DELTA,
            { turn_index: 0, sub_turn_index: 1 },
            { content: "Child answer" }
          ),
        ];
        const state = processPackets(createInitialState(1), packets);
        expect(state.groupKeysWithSectionEnd.has("0-0")).toBe(false);
        expect(state.finalAnswerComing).toBe(false);
        expect(state.toolProcessingDuration).toBeUndefined();
        const result = processPackets(state, [...packets, closing]);
        const parentEnds = (result.groupedPacketsMap.get("0-0") ?? []).filter(
          (packet) =>
            packet.obj.type === PacketType.SECTION_END &&
            packet.placement.sub_turn_index == null
        );
        expect(parentEnds).toHaveLength(1);
        expect(result.groupKeysWithSectionEnd.has("0-0")).toBe(true);
        expect(result.finalAnswerComing).toBe(
          closing.obj.type === PacketType.MESSAGE_START
        );
      }
    }
  );

  test("nested messages preserve the top-level answer timing", () => {
    const state = processPackets(createInitialState(1), [
      createMessageStartPacket({ turn_index: 0 }, 7),
      createMessageStartPacket({ turn_index: 0, sub_turn_index: 0 }, 99),
    ]);
    expect(state.toolProcessingDuration).toBe(7);
  });
});

test.each([undefined, null])(
  "explicit parent ends prevent duplicate closure (%s)",
  (subTurnIndex) => {
    for (const endType of [PacketType.SECTION_END, PacketType.ERROR]) {
      const state = processPackets(createInitialState(1), [
        createSearchToolStartPacket({ turn_index: 0 }),
        createPacket(endType, { turn_index: 0, sub_turn_index: subTurnIndex }),
        createStopPacket(),
      ]);
      const ends = (state.groupedPacketsMap.get("0-0") ?? []).filter(
        (packet) =>
          packet.obj.type === PacketType.SECTION_END ||
          packet.obj.type === PacketType.ERROR
      );
      expect(ends).toHaveLength(1);
    }
  }
);

describe("nested calls", () => {
  const parentStart = createPacket(
    PacketType.RESEARCH_AGENT_START,
    { turn_index: 0 },
    { research_task: "R" }
  );
  const call = (subTurnIndex: number) => ({
    turn_index: 0,
    sub_turn_index: subTurnIndex,
  });

  test("a group exposes its own packets and each nested call once", () => {
    const first = [
      parentStart,
      createSearchToolStartPacket(call(1)),
      createSearchToolStartPacket(call(0)),
    ];
    const state = processPackets(createInitialState(1), first);
    const [group] = state.toolGroups;
    expect(group!.packets).toEqual([parentStart]);
    expect(group!.streamPackets).toEqual(first);
    expect(group!.nestedCalls.map((c) => c.subTurnIndex)).toEqual([0, 1]);
    expect(
      group!.nestedCalls
        .flatMap((c) => c.packets)
        .map((p) => p.placement.sub_turn_index)
    ).toEqual([null, null]);
    expect(group!.nestedCalls.map((c) => c.complete)).toEqual([false, false]);

    const second = [...first, createPacket(PacketType.SECTION_END, call(0))];
    const ended = processPackets(state, second);
    const [afterEnd] = ended.toolGroups;
    expect(afterEnd!.nestedCalls.map((c) => c.complete)).toEqual([true, false]);
    expect(afterEnd!.nestedCalls[1]).toBe(group!.nestedCalls[1]);
    expect(afterEnd!.packets).toEqual([parentStart]);
    expect(ended.groupKeysWithSectionEnd.has("0-0")).toBe(false);

    const report = createPacket(
      PacketType.INTERMEDIATE_REPORT_DELTA,
      { turn_index: 0 },
      { content: "Report" }
    );
    const reported = processPackets(ended, [...second, report]);
    const [afterReport] = reported.toolGroups;
    expect(afterReport!.nestedCalls).toBe(afterEnd!.nestedCalls);
    expect(afterReport!.packets).toEqual([parentStart, report]);
  });
});
