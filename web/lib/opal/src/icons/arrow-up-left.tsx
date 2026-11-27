import type { IconProps } from "@opal/types";

const SvgArrowUpLeft = ({ size, ...props }: IconProps) => (
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
      d="M11.3333 11.3333L5 5M11.3333 4.66663H4.66667V11.3333"
      strokeWidth={1.5}
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgArrowUpLeft;
