import { Badge } from "@/components/ui/badge";
import { PersonaCategory as PersonaCategoryType } from "../admin/assistants/interfaces";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export default function PersonaCategory({
  personaCategory,
}: {
  personaCategory: PersonaCategoryType;
}) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger className="cursor-help">
          <Badge variant="purple">{personaCategory.name}</Badge>
        </TooltipTrigger>
        <TooltipContent>
          <p>{personaCategory.description}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
