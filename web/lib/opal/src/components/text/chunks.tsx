import { Children, type ReactNode } from "react";
import type { TextColor, TextFont } from "@onyx-ai/shared/contracts";
import { Text } from "@opal/components/text/components";

/** Wraps the string parts of a translated rich message in Text so every chunk is a sibling span.
 *  `trim` drops the spaces around words when a flex gap already separates them. */
export function textChunks(
  nodes: ReactNode,
  font: TextFont,
  color: TextColor,
  trim = false
): ReactNode[] {
  return Children.toArray(nodes).map((part, index) =>
    typeof part === "string" ? (
      <Text key={index} font={font} color={color}>
        {trim ? part.trim() : part}
      </Text>
    ) : (
      part
    )
  );
}
