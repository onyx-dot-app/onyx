import { useEffect, useRef } from "react";
import type { Area, CropperProps, Point } from "react-easy-crop";
import {
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import ProfilePhotoCropModal from "@/views/settings/ProfilePhotoCropModal";

const mockToastError = jest.fn();
jest.mock("@opal/layouts", () => ({
  ...jest.requireActual("@opal/layouts"),
  toast: { error: (...args: unknown[]) => mockToastError(...args) },
}));

const PANNED_CROP: Point = { x: -50, y: 0 };

function areaFor(crop: Point): Area {
  return { x: 100 - crop.x, y: 100 - crop.y, width: 200, height: 200 };
}

// jsdom has no layout, so the real cropper never measures its media. This
// stand-in emits its events as react-easy-crop does: the end of a drag emits
// both crop events, and a crop-only prop update emits only the area change.
function mockCropper(props: CropperProps) {
  const { crop, onCropComplete, onCropAreaChange } = props;
  const lastCrop = useRef<Point | null>(null);
  useEffect(() => {
    const area = areaFor(crop);
    if (lastCrop.current === null) {
      onCropComplete?.(area, area);
    }
    if (lastCrop.current?.x !== crop.x || lastCrop.current?.y !== crop.y) {
      onCropAreaChange?.(area, area);
    }
    lastCrop.current = crop;
  });
  return (
    <>
      <img {...props.mediaProps} src={props.image} alt="" />
      <button
        onClick={() => {
          props.onCropChange(PANNED_CROP);
          const area = areaFor(PANNED_CROP);
          onCropComplete?.(area, area);
          onCropAreaChange?.(area, area);
        }}
      >
        Pan
      </button>
    </>
  );
}

jest.mock("react-easy-crop", () => ({
  __esModule: true,
  default: (props: CropperProps) => mockCropper(props),
}));

function renderModal() {
  const onCancel = jest.fn();
  const onSave = jest.fn();
  render(
    <ProfilePhotoCropModal
      file={new File(["photo"], "me.png", { type: "image/png" })}
      onCancel={onCancel}
      onSave={onSave}
    />
  );
  return { onCancel, onSave };
}

describe("ProfilePhotoCropModal", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    URL.createObjectURL = jest.fn(() => "blob:photo");
    URL.revokeObjectURL = jest.fn();
  });

  it("closes with an error when the photo does not decode", () => {
    const { onCancel, onSave } = renderModal();

    const image = screen
      .getByRole("dialog")
      .querySelector("img[src='blob:photo']");
    if (!image) throw new Error("The crop dialog shows no photo");
    fireEvent.error(image);

    expect(mockToastError).toHaveBeenCalledWith(
      "Choose a PNG, JPEG, or WebP image."
    );
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("saves the reset crop after a pan and Reset", async () => {
    const drawImage = jest.fn();
    jest.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage,
      imageSmoothingQuality: "low",
    } as unknown as CanvasRenderingContext2D);
    jest
      .spyOn(HTMLCanvasElement.prototype, "toBlob")
      .mockImplementation((callback) =>
        callback(new Blob(["png"], { type: "image/png" }))
      );
    HTMLImageElement.prototype.decode = jest.fn(() => Promise.resolve());
    const user = setupUser();
    const { onSave } = renderModal();

    await user.click(screen.getByRole("button", { name: "Pan" }));
    await user.click(screen.getByRole("button", { name: "Reset" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const reset = areaFor({ x: 0, y: 0 });
    expect(drawImage).toHaveBeenCalledWith(
      expect.any(HTMLImageElement),
      reset.x,
      reset.y,
      reset.width,
      reset.height,
      0,
      0,
      512,
      512
    );
  });
});
