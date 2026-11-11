import type { IconProps } from "@opal/types";
const SvgArrowLeftDot = ({ size, ...props }: IconProps) => (
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
      d="M2.00002 8H8.50001M5.50002 11.5L2.00002 8L5.50002 4.5M11 8C11 8.82844 11.6716 9.50001 12.5 9.50001C13.3284 9.50001 14 8.82844 14 8C14 7.17156 13.3284 6.50001 12.5 6.50001C11.6716 6.50001 11 7.17156 11 8Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgArrowLeftDot;
