import SvgSearch from "@/icons/search";
import SvgGlobe from "@/icons/globe";
import SvgImage from "@/icons/image";
import { SvgProps } from "@/icons";

// Tool names as referenced by tool results / tool calls
export const SEARCH_TOOL_NAME = "run_search";
export const INTERNET_SEARCH_TOOL_NAME = "run_internet_search";
export const IMAGE_GENERATION_TOOL_NAME = "run_image_generation";

// In-code tool IDs that also correspond to the tool's name when associated with a persona
export const SEARCH_TOOL_ID = "SearchTool";
export const IMAGE_GENERATION_TOOL_ID = "ImageGenerationTool";
export const WEB_SEARCH_TOOL_ID = "WebSearchTool";

// Icon mappings for system tools
export const SYSTEM_TOOL_ICONS: Record<
  string,
  React.FunctionComponent<SvgProps>
> = {
  [SEARCH_TOOL_ID]: SvgSearch,
  [WEB_SEARCH_TOOL_ID]: SvgGlobe,
  [IMAGE_GENERATION_TOOL_ID]: SvgImage,
};
