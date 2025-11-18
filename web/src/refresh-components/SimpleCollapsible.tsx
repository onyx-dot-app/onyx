import { useBoundingBox } from "@/hooks/useBoundingBox";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import { useState } from "react";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgFold from "@/icons/fold";
import SvgExpand from "@/icons/expand";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";

export interface SimpleCollapsibleHeaderProps {
  title: string;
  description?: string;
}

export function SimpleCollapsibleHeader({
  title,
  description,
}: SimpleCollapsibleHeaderProps) {
  return (
    <div className="flex flex-col w-full">
      <Text mainContentEmphasis>{title}</Text>
      {description && (
        <Text secondaryBody text03>
          {description}
        </Text>
      )}
    </div>
  );
}

export interface SimpleCollapsibleProps
  extends React.HtmlHTMLAttributes<HTMLDivElement> {
  trigger: React.ReactNode;
}

export default function SimpleCollapsible({
  trigger,
  className,
  ...rest
}: SimpleCollapsibleProps) {
  const { ref: boundingRef, inside } = useBoundingBox();
  const [open, setOpen] = useState(true);

  return (
    <Collapsible onOpenChange={setOpen} defaultOpen={open}>
      <CollapsibleTrigger asChild>
        <div>
          <div
            ref={boundingRef}
            className="flex flex-row items-center justify-between gap-4 cursor-pointer select-none"
          >
            {trigger}
            <IconButton
              icon={open ? SvgFold : SvgExpand}
              internal
              transient={inside}
              tooltip={open ? "Fold" : "Expand"}
            />
          </div>
        </div>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div {...rest} className={cn("pt-4", className)} />
      </CollapsibleContent>
    </Collapsible>
  );
}
