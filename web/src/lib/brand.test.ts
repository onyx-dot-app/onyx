import { APP_NAME } from "./brand";

describe("brand", () => {
  it("exposes the Glomi AI app name", () => {
    expect(APP_NAME).toBe("Glomi AI");
  });
});
