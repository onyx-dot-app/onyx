import type { IconProps } from "@opal/types/icons";

const SvgArrowRightCircle = ({ size, ...props }: IconProps) => (
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
      d="M7.99999 10.6667L10.6667 8.00001M10.6667 8.00001L7.99999 5.33334M10.6667 8.00001L5.33333 8.00001M14.6667 8.00001C14.6667 11.6819 11.6819 14.6667 7.99999 14.6667C4.3181 14.6667 1.33333 11.6819 1.33333 8.00001C1.33333 4.31811 4.3181 1.33334 7.99999 1.33334C11.6819 1.33334 14.6667 4.31811 14.6667 8.00001Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgArrowRightCircle;
