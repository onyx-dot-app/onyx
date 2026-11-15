import { placeMentions, requestMentions } from "@/lib/chat/mentions";
import type { Mention } from "@/lib/chat/types";

const skill = (name: string): Mention => ({ type: "skill", name });
const at = (name: string, index: number) => ({ ...skill(name), index });

describe("placeMentions", () => {
  it("keeps a mention at its index, next to any text", () => {
    expect(placeMentions("(@triage)x and @triage", [at("triage", 1)])).toEqual([
      at("triage", 1),
    ]);
  });

  it("keeps a plain `@name` beside a tile of the same skill as text", () => {
    expect(placeMentions("@triage then @triage", [at("triage", 13)])).toEqual([
      at("triage", 13),
    ]);
  });

  it("places a mention without an index on its first free `@name`", () => {
    const triage = skill("triage");
    const report = skill("pdf-report");
    expect(
      placeMentions("a@triagez, @pdf-report and @triage", [report, triage])
    ).toEqual([at("triage", 1), at("pdf-report", 11)]);
  });

  it("places a mention whose index no longer holds its `@name` like one without", () => {
    expect(placeMentions("say @triage", [at("triage", 0)])).toEqual([
      at("triage", 4),
    ]);
  });

  it("places longer names first and never overlaps tiles", () => {
    expect(
      placeMentions("@code-review @code", [skill("code"), skill("code-review")])
    ).toEqual([at("code-review", 0), at("code", 13)]);
    expect(
      placeMentions("@code-review", [at("code-review", 0), skill("code")])
    ).toEqual([at("code-review", 0)]);
  });

  it("drops a mention whose `@name` is gone", () => {
    expect(placeMentions("@b and @a", [skill("a"), skill("gone")])).toEqual([
      at("a", 7),
    ]);
  });
});

describe("requestMentions", () => {
  it("sends each mention once, in order, without its index", () => {
    expect(
      requestMentions([at("b", 0), skill("a"), at("b", 9), at("a", 4)])
    ).toEqual([skill("b"), skill("a")]);
  });
});
