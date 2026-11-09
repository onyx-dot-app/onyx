/** A form's first error names what blocks submit, wherever Formik nests it. */
import { firstFormikError } from "@/lib/formikErrors";

describe("firstFormikError", () => {
  it("returns null for no errors", () => {
    expect(firstFormikError({})).toBeNull();
    expect(firstFormikError(undefined)).toBeNull();
  });

  it("returns the first top-level message", () => {
    expect(
      firstFormikError({ name: "Please enter your Name", url: "Bad URL" })
    ).toBe("Please enter your Name");
  });

  it("finds a message nested in objects and arrays", () => {
    expect(
      firstFormikError({
        account: { token: "Please enter your Token" },
      })
    ).toBe("Please enter your Token");
    expect(
      firstFormikError({ channels: [undefined, "Channel cannot be empty"] })
    ).toBe("Channel cannot be empty");
  });
});
