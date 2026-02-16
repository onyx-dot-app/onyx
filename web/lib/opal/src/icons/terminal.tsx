import type { IconProps } from "@opal/types";

const SvgTerminal = ({ size, ...props }: IconProps) => (
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
      d="M2.66667 11.3333L6.66667 7.33331L2.66667 3.33331M8.00001 12.6666H13.3333"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgTerminal;
