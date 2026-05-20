import { SvgArrowExchange } from "@opal/icons";
import { Text } from "@opal/components";

/**
 * Small "Request" / "Response" label used by tool renderers that show a
 * paired input/output (e.g. CustomToolRenderer, CodingAgentRenderer's bash
 * step). Arrow-exchange icon + secondary-body label.
 */
export function IoBlockLabel({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-1">
      <SvgArrowExchange className="w-3 h-3 text-text-02" />
      <Text font="secondary-body" color="text-04">
        {label}
      </Text>
    </div>
  );
}
