import Button from "@/refresh-components/buttons/Button";
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
    // TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved
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
