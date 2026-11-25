import { parseCodeFence } from "@/lib/answerText/codeFence";

test.each([
  ["ts", 'title="src/a.ts"', "ts", "src/a.ts"],
  ["ts", "filename=src/a.ts", "ts", "src/a.ts"],
  ["ts", "src/a.ts", "ts", "src/a.ts"],
  ["ts:src/a.ts", undefined, "ts", "src/a.ts"],
  ["src/a.ts", undefined, "typescript", "src/a.ts"],
  ["main.rs", undefined, "rs", "main.rs"],
  ["python", undefined, "python", undefined],
  [undefined, undefined, undefined, undefined],
])(
  "reads %s %s as language %s and file %s",
  (lang, meta, language, fileName) => {
    expect(parseCodeFence(lang, meta)).toEqual({ language, fileName });
  }
);
