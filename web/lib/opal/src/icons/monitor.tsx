import type { IconProps } from "@opal/types";

const SvgMonitor = ({ size, ...props }: IconProps) => (
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
      d="M5.33334 14H10.6667M8.00001 11.3333V14M2.66668 2H13.3333C14.0697 2 14.6667 2.59695 14.6667 3.33333V10C14.6667 10.7364 14.0697 11.3333 13.3333 11.3333H2.66668C1.9303 11.3333 1.33334 10.7364 1.33334 10V3.33333C1.33334 2.59695 1.9303 2 2.66668 2Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgMonitor;
