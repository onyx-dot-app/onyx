import type { IconProps } from "@opal/types";

const SvgHistory = ({ size, ...props }: IconProps) => (
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
      d="M7.99998 4.00001V8.00001L11 9.50003M1.33332 1.40151V5.23535M1.33332 5.23535H4.99998M1.33332 5.23535L3.28593 3.28597C4.49236 2.07954 6.15903 1.33334 7.99998 1.33334C11.6819 1.33334 14.6667 4.31811 14.6667 8.00001C14.6667 11.6819 11.6819 14.6667 7.99998 14.6667C4.83386 14.6667 2.18324 12.4596 1.50274 9.50003"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgHistory;
