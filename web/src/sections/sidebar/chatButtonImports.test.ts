import fs from "fs";
import path from "path";

// Chat must not depend on Craft code. Craft is a separate product area, and
// a Craft change must not break the chat sidebar.
test("ChatButton does not import Craft code", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "ChatButton.tsx"),
    "utf8"
  );
  expect(source).not.toMatch(/from "@\/app\/craft\//);
});
