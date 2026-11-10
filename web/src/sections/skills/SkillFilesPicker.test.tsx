import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import SkillFilesPicker from "@/sections/skills/SkillFilesPicker";

it("reports a readable error for a corrupt ZIP and allows another selection", async () => {
  const user = setupUser();
  const onChange = jest.fn();
  const onError = jest.fn();
  const errorLog = jest.spyOn(console, "error").mockImplementation(() => {});
  try {
    render(<SkillFilesPicker onChange={onChange} onError={onError} />);
    const input = screen.getByLabelText("Add skill files");
    await user.upload(input, new File(["not a ZIP"], "broken.zip"));
    await waitFor(() =>
      expect(onError).toHaveBeenCalledWith("Could not read the upload.")
    );
    expect(onChange).not.toHaveBeenCalled();
    await user.upload(input, new File(["supporting text"], "notes.txt"));
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
  } finally {
    errorLog.mockRestore();
  }
});
