import { ToolSnapshot } from "@/lib/tools/interfaces";
import { getIconForAction } from "../../services/actionUtils";
import { XIcon } from "@/components/icons/icons";

export function SelectedTool({
  tool,
  onClick,
}: {
  tool: ToolSnapshot;
  onClick: () => void;
}) {
  const Icon = getIconForAction(tool);
  return (
    <div
      className="flex items-center cursor-pointer hover:bg-background-100 rounded-lg p-1"
      onClick={onClick}
    >
      <Icon size={16} />
      <span className="text-sm font-medium select-none ml-1.5 mr-1">
        {tool.display_name}
      </span>
      <XIcon size={12} />
    </div>
  );
}
