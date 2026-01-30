/**
 * Unit tests for packetUtils functions
 * Tests packet type classification and utility functions
 */

import { Packet, PacketType, Placement } from "./streamingModels";
import {
  isToolPacket,
  isActualToolCallPacket,
  isDisplayPacket,
  isSearchToolPacket,
  isStreamingComplete,
  isFinalAnswerComing,
} from "./packetUtils";

// Helper to create a mock packet with a specific type
function createPacket(
  type: PacketType,
  placement?: Partial<Placement>
): Packet {
  return {
    placement: { turn_index: 0, tab_index: 0, ...placement },
    obj: { type } as any,
  };
}

describe("packetUtils", () => {
  describe("isToolPacket", () => {
    const toolPacketTypes = [
      PacketType.SEARCH_TOOL_START,
      PacketType.SEARCH_TOOL_QUERIES_DELTA,
      PacketType.SEARCH_TOOL_DOCUMENTS_DELTA,
      PacketType.PYTHON_TOOL_START,
      PacketType.PYTHON_TOOL_DELTA,
      PacketType.CUSTOM_TOOL_START,
      PacketType.CUSTOM_TOOL_DELTA,
      PacketType.REASONING_START,
      PacketType.REASONING_DELTA,
      PacketType.FETCH_TOOL_START,
      PacketType.FETCH_TOOL_URLS,
      PacketType.FETCH_TOOL_DOCUMENTS,
      PacketType.DEEP_RESEARCH_PLAN_START,
      PacketType.DEEP_RESEARCH_PLAN_DELTA,
      PacketType.RESEARCH_AGENT_START,
      PacketType.INTERMEDIATE_REPORT_START,
      PacketType.INTERMEDIATE_REPORT_DELTA,
      PacketType.INTERMEDIATE_REPORT_CITED_DOCS,
    ];

    test.each(toolPacketTypes)(
      "returns true for tool packet type: %s",
      (packetType) => {
        const packet = createPacket(packetType);
        expect(isToolPacket(packet, false)).toBe(true);
      }
    );

    test("returns true for SECTION_END when includeSectionEnd is true", () => {
      const packet = createPacket(PacketType.SECTION_END);
      expect(isToolPacket(packet, true)).toBe(true);
    });

    test("returns false for SECTION_END when includeSectionEnd is false", () => {
      const packet = createPacket(PacketType.SECTION_END);
      expect(isToolPacket(packet, false)).toBe(false);
    });

    test("returns true for ERROR when includeSectionEnd is true", () => {
      const packet = createPacket(PacketType.ERROR);
      expect(isToolPacket(packet, true)).toBe(true);
    });

    test("returns false for ERROR when includeSectionEnd is false", () => {
      const packet = createPacket(PacketType.ERROR);
      expect(isToolPacket(packet, false)).toBe(false);
    });

    test("returns false for MESSAGE_START", () => {
      const packet = createPacket(PacketType.MESSAGE_START);
      expect(isToolPacket(packet)).toBe(false);
    });

    test("returns false for STOP", () => {
      const packet = createPacket(PacketType.STOP);
      expect(isToolPacket(packet)).toBe(false);
    });
  });

  describe("isActualToolCallPacket", () => {
    const actualToolCallTypes = [
      PacketType.SEARCH_TOOL_START,
      PacketType.SEARCH_TOOL_QUERIES_DELTA,
      PacketType.SEARCH_TOOL_DOCUMENTS_DELTA,
      PacketType.PYTHON_TOOL_START,
      PacketType.PYTHON_TOOL_DELTA,
      PacketType.CUSTOM_TOOL_START,
      PacketType.CUSTOM_TOOL_DELTA,
      PacketType.FETCH_TOOL_START,
      PacketType.FETCH_TOOL_URLS,
      PacketType.FETCH_TOOL_DOCUMENTS,
      PacketType.DEEP_RESEARCH_PLAN_START,
      PacketType.DEEP_RESEARCH_PLAN_DELTA,
      PacketType.RESEARCH_AGENT_START,
      PacketType.INTERMEDIATE_REPORT_START,
      PacketType.INTERMEDIATE_REPORT_DELTA,
      PacketType.INTERMEDIATE_REPORT_CITED_DOCS,
    ];

    test.each(actualToolCallTypes)(
      "returns true for actual tool call type: %s",
      (packetType) => {
        const packet = createPacket(packetType);
        expect(isActualToolCallPacket(packet)).toBe(true);
      }
    );

    test("returns false for REASONING_START (this is the key fix)", () => {
      const packet = createPacket(PacketType.REASONING_START);
      expect(isActualToolCallPacket(packet)).toBe(false);
    });

    test("returns false for REASONING_DELTA (this is the key fix)", () => {
      const packet = createPacket(PacketType.REASONING_DELTA);
      expect(isActualToolCallPacket(packet)).toBe(false);
    });

    test("returns false for MESSAGE_START", () => {
      const packet = createPacket(PacketType.MESSAGE_START);
      expect(isActualToolCallPacket(packet)).toBe(false);
    });

    test("returns false for STOP", () => {
      const packet = createPacket(PacketType.STOP);
      expect(isActualToolCallPacket(packet)).toBe(false);
    });

    test("returns false for SECTION_END", () => {
      const packet = createPacket(PacketType.SECTION_END);
      expect(isActualToolCallPacket(packet)).toBe(false);
    });

    test("returns false for ERROR", () => {
      const packet = createPacket(PacketType.ERROR);
      expect(isActualToolCallPacket(packet)).toBe(false);
    });

    // Test that isActualToolCallPacket is consistent with isToolPacket
    // (i.e., it's a subset of tool packets minus reasoning)
    test("isActualToolCallPacket is isToolPacket minus reasoning packets", () => {
      // All actual tool call types should also be tool packets
      actualToolCallTypes.forEach((packetType) => {
        const packet = createPacket(packetType);
        expect(isToolPacket(packet, false)).toBe(true);
        expect(isActualToolCallPacket(packet)).toBe(true);
      });

      // Reasoning packets should be tool packets but NOT actual tool calls
      const reasoningPacket1 = createPacket(PacketType.REASONING_START);
      const reasoningPacket2 = createPacket(PacketType.REASONING_DELTA);

      expect(isToolPacket(reasoningPacket1, false)).toBe(true);
      expect(isActualToolCallPacket(reasoningPacket1)).toBe(false);

      expect(isToolPacket(reasoningPacket2, false)).toBe(true);
      expect(isActualToolCallPacket(reasoningPacket2)).toBe(false);
    });
  });

  describe("isDisplayPacket", () => {
    test("returns true for MESSAGE_START", () => {
      const packet = createPacket(PacketType.MESSAGE_START);
      expect(isDisplayPacket(packet)).toBe(true);
    });

    test("returns true for IMAGE_GENERATION_TOOL_START", () => {
      const packet = createPacket(PacketType.IMAGE_GENERATION_TOOL_START);
      expect(isDisplayPacket(packet)).toBe(true);
    });

    test("returns true for PYTHON_TOOL_START", () => {
      const packet = createPacket(PacketType.PYTHON_TOOL_START);
      expect(isDisplayPacket(packet)).toBe(true);
    });

    test("returns false for other packet types", () => {
      const packet = createPacket(PacketType.SEARCH_TOOL_START);
      expect(isDisplayPacket(packet)).toBe(false);
    });
  });

  describe("isSearchToolPacket", () => {
    test("returns true for SEARCH_TOOL_START", () => {
      const packet = createPacket(PacketType.SEARCH_TOOL_START);
      expect(isSearchToolPacket(packet)).toBe(true);
    });

    test("returns true for SEARCH_TOOL_QUERIES_DELTA", () => {
      const packet = createPacket(PacketType.SEARCH_TOOL_QUERIES_DELTA);
      expect(isSearchToolPacket(packet)).toBe(true);
    });

    test("returns true for SEARCH_TOOL_DOCUMENTS_DELTA", () => {
      const packet = createPacket(PacketType.SEARCH_TOOL_DOCUMENTS_DELTA);
      expect(isSearchToolPacket(packet)).toBe(true);
    });

    test("returns false for other packet types", () => {
      const packet = createPacket(PacketType.PYTHON_TOOL_START);
      expect(isSearchToolPacket(packet)).toBe(false);
    });
  });

  describe("isStreamingComplete", () => {
    test("returns true when packets contain STOP", () => {
      const packets = [
        createPacket(PacketType.MESSAGE_START),
        createPacket(PacketType.MESSAGE_DELTA),
        createPacket(PacketType.STOP),
      ];
      expect(isStreamingComplete(packets)).toBe(true);
    });

    test("returns false when packets do not contain STOP", () => {
      const packets = [
        createPacket(PacketType.MESSAGE_START),
        createPacket(PacketType.MESSAGE_DELTA),
      ];
      expect(isStreamingComplete(packets)).toBe(false);
    });

    test("returns false for empty array", () => {
      expect(isStreamingComplete([])).toBe(false);
    });
  });

  describe("isFinalAnswerComing", () => {
    test("returns true when packets contain MESSAGE_START", () => {
      const packets = [
        createPacket(PacketType.SEARCH_TOOL_START),
        createPacket(PacketType.MESSAGE_START),
      ];
      expect(isFinalAnswerComing(packets)).toBe(true);
    });

    test("returns true when packets contain IMAGE_GENERATION_TOOL_START", () => {
      const packets = [createPacket(PacketType.IMAGE_GENERATION_TOOL_START)];
      expect(isFinalAnswerComing(packets)).toBe(true);
    });

    test("returns true when packets contain PYTHON_TOOL_START", () => {
      const packets = [createPacket(PacketType.PYTHON_TOOL_START)];
      expect(isFinalAnswerComing(packets)).toBe(true);
    });

    test("returns false when no display packets present", () => {
      const packets = [
        createPacket(PacketType.SEARCH_TOOL_START),
        createPacket(PacketType.REASONING_START),
      ];
      expect(isFinalAnswerComing(packets)).toBe(false);
    });

    test("returns false for empty array", () => {
      expect(isFinalAnswerComing([])).toBe(false);
    });
  });
});
