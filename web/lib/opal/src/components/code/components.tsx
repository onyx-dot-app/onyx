"use client";

import { useState } from "react";
import type { WithoutStyles } from "@opal/types";
import { Hoverable } from "@opal/core";
import { Button } from "@opal/components/buttons/button/components";
import { copyText } from "@opal/utils";
import SvgCheck from "@opal/icons/check";
import SvgCopy from "@opal/icons/copy";
import "@opal/components/code/styles.css";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CodeProps extends WithoutStyles<React.HTMLAttributes<HTMLElement>> {
  children: string;
  /** Show copy-to-clipboard button on hover. @default true */
  showCopyButton?: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Code({ children, showCopyButton = true, ...props }: CodeProps) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    copyText(children)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 3000);
      })
      .catch(() => {});
  }

  return (
    <div className="opal-code-root">
      <Hoverable.Root group="code">
        <code className="opal-code" {...props}>
          {children}
        </code>
        {showCopyButton && (
          <Hoverable.Item group="code">
            <div className="opal-code-copy">
              <Button
                size="xs"
                prominence="tertiary"
                icon={copied ? SvgCheck : SvgCopy}
                onClick={handleCopy}
                tooltip={copied ? "Copied!" : "Copy"}
                aria-label="Copy code"
              />
            </div>
          </Hoverable.Item>
        )}
      </Hoverable.Root>
    </div>
  );
}
