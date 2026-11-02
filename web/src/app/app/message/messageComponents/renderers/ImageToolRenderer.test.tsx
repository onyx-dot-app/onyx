import { render, screen } from "@tests/setup/test-utils";
import { ImageToolRenderer } from "@/app/app/message/messageComponents/renderers/ImageToolRenderer";
import { RenderType } from "@/app/app/message/messageComponents/types";
import {
  ImageGenerationToolPacket,
  PacketType,
} from "@/app/app/services/streamingModels";

test("the timeline counts unique images across repeated deltas", () => {
  const image = {
    file_id: "first",
    url: "/api/chat/file/first",
    revised_prompt: "An onyx stone",
  };
  const packets: ImageGenerationToolPacket[] = [
    {
      placement: { turn_index: 0 },
      obj: { type: PacketType.IMAGE_GENERATION_TOOL_START },
    },
    {
      placement: { turn_index: 0 },
      obj: {
        type: PacketType.IMAGE_GENERATION_TOOL_DELTA,
        images: [{ ...image }],
      },
    },
    {
      placement: { turn_index: 0 },
      obj: {
        type: PacketType.IMAGE_GENERATION_TOOL_DELTA,
        images: [{ ...image }],
      },
    },
    { placement: { turn_index: 0 }, obj: { type: PacketType.SECTION_END } },
  ];
  render(
    <ImageToolRenderer
      packets={packets}
      state={{}}
      onComplete={() => {}}
      renderType={RenderType.COMPACT}
      animate={false}
      stopPacketSeen
    >
      {(steps) => <>{steps[0]?.status}</>}
    </ImageToolRenderer>
  );
  expect(screen.getByText("Generated 1 image")).toBeInTheDocument();
});

test.each([
  { hasResult: true, expectedStatus: "No images generated" },
  { hasResult: false, expectedStatus: "Image generation stopped" },
])(
  "renders $expectedStatus for an image step without images",
  ({ hasResult, expectedStatus }) => {
    const packets: ImageGenerationToolPacket[] = [
      {
        placement: { turn_index: 0 },
        obj: { type: PacketType.IMAGE_GENERATION_TOOL_START },
      },
    ];
    if (hasResult) {
      packets.push({
        placement: { turn_index: 0 },
        obj: { type: PacketType.IMAGE_GENERATION_TOOL_DELTA, images: [] },
      });
    }
    // The packet processor also inserts SECTION_END for groups closed by STOP.
    packets.push({
      placement: { turn_index: 0 },
      obj: { type: PacketType.SECTION_END },
    });
    render(
      <ImageToolRenderer
        packets={packets}
        state={{}}
        onComplete={() => {}}
        renderType={RenderType.COMPACT}
        animate={false}
        stopPacketSeen
      >
        {(steps) => <>{steps[0]?.status}</>}
      </ImageToolRenderer>
    );
    expect(screen.getByText(expectedStatus)).toBeInTheDocument();
  }
);
