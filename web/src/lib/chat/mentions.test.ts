import { findMentions, mentionsInText } from "@/lib/chat/mentions";
import type { Mention } from "@/lib/chat/types";

const skill = (name: string): Mention => ({ type: "skill", name });

describe("findMentions", () => {
  it("finds whole-token mentions in text order", () => {
    const triage = skill("triage");
    const report = skill("pdf-report");
    expect(
      findMentions("@triage then @pdf-report, and\n@triage", [report, triage])
    ).toEqual([
      { index: 0, mention: triage },
      { index: 13, mention: report },
      { index: 30, mention: triage },
    ]);
  });

  // The `@` menu opens on the same token starts.
  it("skips emails, mid-token mentions, longer names and other triggers", () => {
    expect(
      findMentions("a@triage (@triage @triage-v2 @@triage $triage", [
        skill("triage"),
      ])
    ).toEqual([]);
  });
});

describe("mentionsInText", () => {
  it("keeps the mentions whose name is still in the text, in their order", () => {
    const [a, gone, b] = [skill("a"), skill("gone"), skill("b")];
    expect(mentionsInText("@b and @a", [a, gone, b])).toEqual([a, b]);
  });
});
