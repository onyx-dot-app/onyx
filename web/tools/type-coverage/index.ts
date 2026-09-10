import { writeFileSync } from "node:fs";
import { sep } from "node:path";
import { parseArgs } from "node:util";

import { lint } from "type-coverage-core";

// Measures TypeScript type coverage for web/: the share of identifiers whose
// type is not `any`. `ods type-coverage typescript` groups these per-file
// counts into directories and gates them against .type-coverage-baseline.yaml.

interface FileCount {
  file: string;
  correct: number;
  total: number;
}

const { values } = parseArgs({
  options: { output: { type: "string" } },
});

const result = await lint("tsconfig.types.json", {
  // Non-strict counts only `any`. Strict also counts casts and `!`, which the
  // anti-slop lint rules cover. Changing the mode moves every floor.
  strict: false,
  fileCounts: true,
  // Ignored files stay in the program, so their types still resolve.
  // - .next/dev/types exists only after `next dev`, so counting it would change
  //   the rows between machines.
  // - lib/ holds workspace packages that tsconfig.types.json excludes. Only
  //   the files web/ imports would count, so the rows would move with imports.
  ignoreFiles: [".next/**", "lib/**"],
});

// Keys are relative to process.cwd(), which `bun run` sets to web/.
const files: FileCount[] = Array.from(result.fileCounts, ([file, counts]) => ({
  file: file.split(sep).join("/"),
  correct: counts.correctCount,
  total: counts.totalCount,
})).sort((a, b) => (a.file < b.file ? -1 : 1));

if (values.output === undefined) {
  const percent =
    result.totalCount === 0
      ? 100
      : (result.correctCount / result.totalCount) * 100;
  console.log(
    `Type coverage: ${percent.toFixed(2)}% (${result.correctCount} of ${result.totalCount} identifiers) across ${files.length} files`
  );
} else {
  writeFileSync(values.output, `${JSON.stringify({ files }, null, 2)}\n`);
}
