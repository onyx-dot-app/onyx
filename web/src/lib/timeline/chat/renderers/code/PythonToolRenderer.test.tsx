import { render, waitFor } from "@tests/setup/test-utils";
import { PythonToolRenderer } from "@/lib/timeline/chat/renderers/code/PythonToolRenderer";
import { RenderType } from "@/lib/timeline/chat/message/messageComponents/types";
import {
  PacketType,
  PythonToolPacket,
} from "@/app/app/services/streamingModels";

const MALICIOUS_CODE = '<img src="x" onerror="window.__pwned=1">';

test("escapes the code in highlighted lines", async () => {
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

  await waitFor(() =>
    expect(container.querySelector('span[style*="--shiki"]')).not.toBeNull()
  );
  expect(container.querySelector("img")).toBeNull();
  expect(container.textContent).toContain(MALICIOUS_CODE);
});
