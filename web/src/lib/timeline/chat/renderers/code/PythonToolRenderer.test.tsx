import hljs from "highlight.js/lib/core";
import { render } from "@tests/setup/test-utils";
import { PythonToolRenderer } from "@/lib/timeline/chat/renderers/code/PythonToolRenderer";
import { RenderType } from "@/app/app/message/messageComponents/types";
import {
  PacketType,
  PythonToolPacket,
} from "@/app/app/services/streamingModels";

const MALICIOUS_CODE = '<img src="x" onerror="window.__pwned=1">';

afterEach(() => {
  jest.restoreAllMocks();
});

test("escapes the code when syntax highlighting fails", () => {
  jest.spyOn(hljs, "highlight").mockImplementation(() => {
    throw new Error("highlight failed");
  });
  const packets: PythonToolPacket[] = [
    {
      placement: { turn_index: 0 },
      obj: { type: PacketType.PYTHON_TOOL_START, code: MALICIOUS_CODE },
    },
  ];

  const { container } = render(
    <PythonToolRenderer
      packets={packets}
      nestedCalls={[]}
      state={{}}
      onComplete={() => {}}
      renderType={RenderType.FULL}
      animate={false}
      stopPacketSeen={false}
    >
      {(results) => <section>{results[0]?.content}</section>}
    </PythonToolRenderer>
  );

  expect(container.querySelector("img")).toBeNull();
  expect(container.textContent).toContain(MALICIOUS_CODE);
});
