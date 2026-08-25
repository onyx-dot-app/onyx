import { Button } from "@opal/components";
import { cn } from "@opal/utils";
import { SvgChevronRight } from "@opal/icons";
interface AdvancedOptionsToggleProps {
  showAdvancedOptions: boolean;
  setShowAdvancedOptions: (show: boolean) => void;
  title?: string;
}

export function AdvancedOptionsToggle({
  showAdvancedOptions,
  setShowAdvancedOptions,
  title,
}: AdvancedOptionsToggleProps) {
  return (
    <div className="mr-auto">
      <Button
        prominence="internal"
        icon={({ className, style }) => (
          // `style` carries the icon sizing that opal's `iconWrapper` applies,
          // so an icon function has to forward it.
          <SvgChevronRight
            className={cn(className, showAdvancedOptions && "rotate-90")}
            style={style}
          />
        )}
        onClick={() => setShowAdvancedOptions(!showAdvancedOptions)}
      >
        {title || "Advanced Options"}
      </Button>
    </div>
  );
}
