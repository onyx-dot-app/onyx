import type { IconProps } from "@/index";

const SvgMaximize2 = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 14 14"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M9 1H13M13 1V5M13 1L8.33333 5.66667M5 13H1M1 13V9M1 13L5.66667 8.33333"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgMaximize2;
