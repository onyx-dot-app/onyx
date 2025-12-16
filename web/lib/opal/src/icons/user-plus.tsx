import type { IconProps } from "@opal/types";
const SvgUserPlus = ({ size, ...props }: IconProps) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M11 14C11 13.6667 11 13.3333 11 13C11 11.3431 9.65684 10 7.99998 10H4.00002C2.34316 10 1 11.3431 1 13C1 13.3333 1 13.6667 1 14M10.75 7.50005L12.75 7.50007M12.75 7.50007H14.75M12.75 7.50007V9.5M12.75 7.50007V5.5M8.75 4.75C8.75 6.26878 7.51878 7.5 6 7.5C4.48122 7.5 3.25 6.26878 3.25 4.75C3.25 3.23122 4.48122 2 6 2C7.51878 2 8.75 3.23122 8.75 4.75Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgUserPlus;
