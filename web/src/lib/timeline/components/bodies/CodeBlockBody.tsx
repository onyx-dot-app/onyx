"use client";

import { CodePanel } from "@opal/components";
import { useCodeLines } from "@/lib/timeline/components/bodies/useCodeLines";

interface CodeBlockBodyProps {
  code: string;
  /** The fence's language tag. Untagged code is guessed once it is done. */
  language?: string;
  /** The code still streams in: highlight it line by line, guess nothing. */
  streaming?: boolean;
}

/**
 * A fenced code block in answer text, as an Opal `CodePanel`, so it looks
 * like code in a tool card. Tagged code gets a title row with its language
 * and a copy button; untagged code gets a copy button on hover. A guessed
 * language colors the code but is not shown: a wrong guess would read as a
 * fact.
 */
export function CodeBlockBody({
  code,
  language,
  streaming = false,
}: CodeBlockBodyProps) {
  const lines = useCodeLines(code, language, {
    streaming,
    detect: !language,
  });

  return (
    <CodePanel>
      {language && <CodePanel.Header title={language} copyText={code} />}
      {/* Answer code grows with its lines, so streaming code stays in view
          as the page follows it. */}
      <CodePanel.Lines
        lines={lines}
        copyText={language ? undefined : code}
        grow
      />
    </CodePanel>
  );
}

export default CodeBlockBody;
