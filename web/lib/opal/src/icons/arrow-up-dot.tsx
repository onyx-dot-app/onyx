import type { IconProps } from "@opal/types";
const SvgArrowUpDot = ({ size, ...props }: IconProps) => (
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
      d="M8.00002 2V8.49999M11.5 5.5L8.00002 2L4.5 5.5M8.00002 11C8.82845 11 9.50003 11.6716 9.50003 12.5C9.50003 13.3284 8.82845 14 8.00002 14C7.17158 14 6.50003 13.3284 6.50003 12.5C6.50003 11.6716 7.17158 11 8.00002 11Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgArrowUpDot;
