import { render } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import { act } from "@testing-library/react";
import { InputSingleUpload } from "@opal/components";

class DeferredReader {
  static all: DeferredReader[] = [];
  result: string | null = null;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private name = "";
  constructor() {
    DeferredReader.all.push(this);
  }
  readAsText(file: File) {
    this.name = file.name;
  }
  finish() {
    this.result = `{"name": "${this.name}"}`;
    this.onload?.();
  }
}

test("an older read ending does not end a newer one", async () => {
  const original = global.FileReader;
  global.FileReader = DeferredReader as unknown as typeof FileReader;
  try {
    const onReadingChange = jest.fn();
    const { container } = render(
      <InputSingleUpload
        setValue={jest.fn()}
        onReadingChange={onReadingChange}
      />
    );
    const input =
      container.querySelector<HTMLInputElement>('input[type="file"]')!;
    await userEvent.upload(input, new File(["a"], "a.json"));
    await userEvent.upload(input, new File(["b"], "b.json"));
    const [first, second] = DeferredReader.all;

    act(() => first!.finish());
    expect(onReadingChange).toHaveBeenLastCalledWith(true);

    act(() => second!.finish());
    expect(onReadingChange).toHaveBeenLastCalledWith(false);
  } finally {
    global.FileReader = original;
  }
});
