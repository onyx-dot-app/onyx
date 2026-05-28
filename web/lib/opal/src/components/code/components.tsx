"use client";

import { useState } from "react";
import type { WithoutStyles } from "@opal/types";
import { Hoverable } from "@opal/core";
import { Button } from "@opal/components/buttons/button/components";
import SvgCheck from "@opal/icons/check";
import SvgCopy from "@opal/icons/copy";

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
    navigator.clipboard.writeText(children).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 3000);
    });
  }

  return (
    <div className="relative w-full">
      <Hoverable.Root group="code">
        <code
          className="block p-2 bg-background-tint-00 border border-border-01 rounded-12 break-all whitespace-pre-wrap font-secondary-mono text-text-03 w-full"
          {...props}
        >
          {children}
        </code>
        {showCopyButton && (
          <Hoverable.Item group="code">
            <div className="absolute top-2 right-2">
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
