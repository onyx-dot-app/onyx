import SvgSearch from "@/icons/search";
import SvgGlobe from "@/icons/globe";
import SvgImage from "@/icons/image";
import SvgCode from "@/icons/code";
import SvgLink from "@/icons/link";
import { IconProps } from "@/icons";

// Tool names as referenced by tool results / tool calls
export const SEARCH_TOOL_NAME = "run_search";
export const INTERNET_SEARCH_TOOL_NAME = "run_internet_search";
export const IMAGE_GENERATION_TOOL_NAME = "run_image_generation";
export const PYTHON_TOOL_NAME = "run_python";
export const OPEN_URL_TOOL_NAME = "open_url";

// In-code tool IDs that also correspond to the tool's name when associated with a persona
export const SEARCH_TOOL_ID = "SearchTool";
export const IMAGE_GENERATION_TOOL_ID = "ImageGenerationTool";
export const WEB_SEARCH_TOOL_ID = "WebSearchTool";
export const PYTHON_TOOL_ID = "PythonTool";
export const OPEN_URL_TOOL_ID = "OpenURLTool";

// Icon mappings for system tools
export const SYSTEM_TOOL_ICONS: Record<
  string,
  React.FunctionComponent<IconProps>
> = {
  [SEARCH_TOOL_ID]: SvgSearch,
  [WEB_SEARCH_TOOL_ID]: SvgGlobe,
  [IMAGE_GENERATION_TOOL_ID]: SvgImage,
  [PYTHON_TOOL_ID]: SvgCode,
  [OPEN_URL_TOOL_ID]: SvgLink,
};
