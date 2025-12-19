import type { IconProps } from "@opal/types";

const SvgFilter = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M14.6667 3H1.33334L6.66668 9.30667V12.6667L9.33334 14V9.30667L14.6667 3Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgFilter;
