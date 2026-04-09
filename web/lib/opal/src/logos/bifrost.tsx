import { cn } from "@opal/utils";
import type { IconProps } from "@opal/types";

const SvgBifrost = ({ size, className, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 37 46"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={cn(className, "!text-[#33C19E]")}
    {...props}
  >
    <title>Bifrost</title>
    <path
      d="M27.6219 46H0V36.8H27.6219V46ZM36.8268 36.8H27.6219V27.6H36.8268V36.8ZM18.4146 27.6H9.2073V18.4H18.4146V27.6ZM36.8268 18.4H27.6219V9.2H36.8268V18.4ZM27.6219 9.2H0V0H27.6219V9.2Z"
      fill="currentColor"
    />
  </svg>
);

export default SvgBifrost;
