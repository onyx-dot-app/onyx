"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, CodePanel } from "@opal/components";
import { SvgTextWrap } from "@opal/icons";
import { useCodeLines } from "@/lib/timeline/components/bodies/useCodeLines";

const UNTAGGED_LANGUAGE = "text";

interface CodeBlockBodyProps {
  code: string;
  /** The fence's language. Untagged code shows plain. */
  language?: string;
  /** A file name from the fence, shown in place of the language. */
  fileName?: string;
  /** The code still streams in: its last line shows plain. */
  streaming?: boolean;
}

/**
 * A fenced code block in answer text, as an Opal `CodePanel`, so it looks
 * like code in a tool card. Every block gets a title row with its file name
 * or language, a wrap toggle and a copy button.
 */
export function CodeBlockBody({
  code,
  language,
  fileName,
  streaming = false,
}: CodeBlockBodyProps) {
  const t = useTranslations("chat.messages.codeBlock.wrapButton");
  const [wrap, setWrap] = useState(true);
  const lines = useCodeLines(code, language, { streaming });
  const wrapLabel = wrap ? t("unwrapLabel") : t("wrapLabel");

  return (
    <CodePanel>
      <CodePanel.Header
        title={fileName ?? language ?? UNTAGGED_LANGUAGE}
        copyText={code}
        rightChildren={
          <Button
            icon={SvgTextWrap}
            size="2xs"
            prominence="tertiary"
            tooltip={wrapLabel}
            aria-label={wrapLabel}
            onClick={() => setWrap(!wrap)}
          />
        }
      />
      {/* Answer code grows with its lines, so streaming code stays in view
          as the page follows it. */}
      <CodePanel.Lines lines={lines} grow wrap={wrap} />
    </CodePanel>
  );
}

export default CodeBlockBody;
