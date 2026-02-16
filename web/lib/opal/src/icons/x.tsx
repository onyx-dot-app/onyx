import type { IconProps } from "@opal/types";

const SvgX = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 28 28"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    strokeWidth={2.5}
    {...props}
  >
    <path d="M21 7L7 21M7 7L21 21" strokeLinejoin="round" />
  </svg>
);
export default SvgX;
