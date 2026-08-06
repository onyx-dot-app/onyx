import { isPowerPointPath } from "@/app/craft/utils/fileTypes";

describe("isPowerPointPath", () => {
  test.each([
    "outputs/presentation.ppt",
    "outputs/presentation.pptx",
    "outputs/PRESENTATION.PPT",
    "outputs/PRESENTATION.PPTX",
  ])("recognizes PowerPoint file %s", (path) => {
    expect(isPowerPointPath(path)).toBe(true);
  });

  test.each([
    "outputs/presentation.pdf",
    "outputs/presentation.pptx.txt",
    "outputs/presentation",
  ])("rejects non-PowerPoint file %s", (path) => {
    expect(isPowerPointPath(path)).toBe(false);
  });
});
