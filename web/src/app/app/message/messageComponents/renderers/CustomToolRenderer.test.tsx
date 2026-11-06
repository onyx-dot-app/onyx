import { render, screen } from "@tests/setup/test-utils";
import {
  CustomToolErrorInfo,
  CustomToolPacket,
  PacketType,
} from "@/app/app/services/streamingModels";
import { RenderType } from "@/app/app/message/messageComponents/types";
import { CustomToolRenderer } from "@/app/app/message/messageComponents/renderers/CustomToolRenderer";

const placement = { turn_index: 0, tab_index: 0 };

function packets(error: CustomToolErrorInfo): CustomToolPacket[] {
  return [
    {
      placement,
      obj: { type: PacketType.CUSTOM_TOOL_START, tool_name: "get_meta_data" },
    },
    {
      placement,
      obj: {
        type: PacketType.CUSTOM_TOOL_DELTA,
        tool_name: "get_meta_data",
        response_type: "text",
        error,
      },
    },
    { placement, obj: { type: PacketType.SECTION_END } },
  ] as CustomToolPacket[];
}

function renderStatus(error: CustomToolErrorInfo) {
  render(
    <CustomToolRenderer
      packets={packets(error)}
      state={{}}
      onComplete={jest.fn()}
      renderType={RenderType.FULL}
      animate={false}
      stopPacketSeen
    >
      {(results) => (
        <div>
          {results.map((result, index) => (
            <div
              key={index}
              data-surface={result.surfaceBackground}
              data-collapsible={String(result.supportsCollapsible)}
            >
              {result.status}
              {result.content}
            </div>
          ))}
        </div>
      )}
    </CustomToolRenderer>
  );
}

describe("CustomToolRenderer", () => {
  test("shows a blocked destination as blocked on the error surface", () => {
    const message =
      "The get_meta_data tool could not run because its destination is not allowed.";
    renderStatus({
      is_auth_error: false,
      is_unreachable: false,
      status_code: null,
      message,
    });

    expect(screen.getByText("get_meta_data was blocked")).toBeInTheDocument();
    expect(screen.queryByText(/completed/)).not.toBeInTheDocument();
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(
      screen.getByText("get_meta_data was blocked").closest("[data-surface]")
    ).toHaveAttribute("data-surface", "error");
    expect(
      screen.getByText("get_meta_data was blocked").closest("[data-surface]")
    ).toHaveAttribute("data-collapsible", "false");
  });

  test("shows an unreachable server as unreachable, not blocked", () => {
    const message =
      "The get_meta_data tool could not reach its server (timed out).";
    renderStatus({
      is_auth_error: false,
      is_unreachable: true,
      status_code: null,
      message,
    });

    const status = screen.getByText("get_meta_data could not reach its server");
    expect(screen.queryByText(/was blocked/)).not.toBeInTheDocument();
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(status.closest("[data-surface]")).toHaveAttribute(
      "data-surface",
      "error"
    );
  });

  test("shows an HTTP failure with its status code", () => {
    renderStatus({
      is_auth_error: false,
      is_unreachable: false,
      status_code: 502,
      message: "Bad",
    });

    expect(screen.queryByText(/completed/)).not.toBeInTheDocument();
    expect(screen.queryByText(/was blocked/)).not.toBeInTheDocument();
    expect(screen.getByText(/502/)).toBeInTheDocument();
  });
});
