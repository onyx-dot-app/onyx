import type { IconProps } from "@opal/types";

const SvgArrowUpRight = ({ size, ...props }: IconProps) => (
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
      d="M4.66667 11.3333L11 5M4.66667 4.66663H11.3333V11.3333"
      strokeWidth={1.5}
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgArrowUpRight;
