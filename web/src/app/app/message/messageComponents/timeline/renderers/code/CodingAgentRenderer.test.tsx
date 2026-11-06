import { render, screen } from "@tests/setup/test-utils";
import { CodingAgentRenderer } from "@/app/app/message/messageComponents/timeline/renderers/code/CodingAgentRenderer";
import { RenderType } from "@/app/app/message/messageComponents/types";
import {
  CodingAgentPacket,
  PacketType,
} from "@/app/app/services/streamingModels";

function CodingOutput({ packets }: { packets: CodingAgentPacket[] }) {
  return (
    <CodingAgentRenderer
      packets={packets}
      state={{}}
      onComplete={() => {}}
      renderType={RenderType.FULL}
      animate={false}
      stopPacketSeen={false}
    >
      {(results) => (
        <section aria-label="Coding output">{results[0]?.content}</section>
      )}
    </CodingAgentRenderer>
  );
}

test("parallel commands retain their own output and completion status", () => {
  const packets: CodingAgentPacket[] = [
    {
      placement: { turn_index: 0, sub_turn_index: 1 },
      obj: { type: PacketType.BASH_TOOL_START, cmd: "first-command" },
    },
    {
      placement: { turn_index: 0, sub_turn_index: 2 },
      obj: { type: PacketType.BASH_TOOL_START, cmd: "second-command" },
    },
    {
      placement: { turn_index: 0, sub_turn_index: 2 },
      obj: {
        type: PacketType.BASH_TOOL_DELTA,
        stdout: "second-output",
        stderr: "",
        exit_code: 7,
        timed_out: false,
      },
    },
    {
      placement: { turn_index: 0, sub_turn_index: 1 },
      obj: {
        type: PacketType.BASH_TOOL_DELTA,
        stdout: "first-output",
        stderr: "",
        exit_code: null,
        timed_out: false,
      },
    },
  ];
  const { rerender } = render(<CodingOutput packets={packets} />);

  expect(
    screen.getByRole("region", { name: "Coding output" })
  ).toHaveTextContent(
    /first-command.*first-output.*second-command.*second-output/
  );
  expect(screen.getByText("Bash · running…")).toBeInTheDocument();
  expect(screen.getByText("Bash · exit 7")).toBeInTheDocument();

  rerender(
    <CodingOutput
      packets={[
        ...packets,
        {
          placement: { turn_index: 0, sub_turn_index: 1 },
          obj: { type: PacketType.SECTION_END },
        },
      ]}
    />
  );
  expect(screen.queryByText("Bash · running…")).not.toBeInTheDocument();
});

test("saved sequential commands can reuse the same section", () => {
  const packets: CodingAgentPacket[] = ["first", "second"].flatMap((name) => [
    {
      placement: { turn_index: 0 },
      obj: { type: PacketType.BASH_TOOL_START, cmd: `${name}-command` },
    },
    {
      placement: { turn_index: 0 },
      obj: {
        type: PacketType.BASH_TOOL_DELTA,
        stdout: `${name}-output`,
        stderr: "",
        exit_code: 0,
        timed_out: false,
      },
    },
  ]);
  render(<CodingOutput packets={packets} />);
  expect(
    screen.getByRole("region", { name: "Coding output" })
  ).toHaveTextContent(
    /first-command.*first-output.*second-command.*second-output/
  );
});
