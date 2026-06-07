import type { IconProps } from "@opal/types";
import { cn } from "@opal/utils";
import SvgLoader from "@opal/icons/loader";

const SvgSimpleLoader = ({ className, ...props }: IconProps) => (
  <SvgLoader className={cn("h-4 w-4 animate-spin", className)} {...props} />
);

export default SvgSimpleLoader;
