import Button from "@/refresh-components/buttons/Button";
import { cn } from "@/lib/utils";
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
    // TODO(opal-migration): migrate to opal Button once className/iconClassName is removed
    <Button
      internal
      leftIcon={({ className }) => (
        <SvgChevronRight
          className={cn(className, showAdvancedOptions && "rotate-90")}
        />
      )}
      onClick={() => setShowAdvancedOptions(!showAdvancedOptions)}
      className="mr-auto"
    >
      {title || "Advanced Options"}
    </Button>
  );
}
