import type { IconProps } from "@opal/types";
const SvgArrowRightDot = ({ size, ...props }: IconProps) => (
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
      d="M14 8H7.50002M10.5 11.5L14 8L10.5 4.5M5.00002 8C5.00002 8.82844 4.32844 9.50001 3.50001 9.50001C2.67159 9.50001 2.00002 8.82844 2.00002 8C2.00002 7.17156 2.67159 6.50001 3.50001 6.50001C4.32844 6.50001 5.00002 7.17156 5.00002 8Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgArrowRightDot;
