import type { IconProps } from "@opal/types";
const SvgCurate = ({ size, ...props }: IconProps) => (
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
      d="M8 9L8 14.5M8 9C7.35971 8.35971 6.9055 8 6 8H2.5L2.5 13.5H6C6.9055 13.5 7.35971 13.8597 8 14.5M8 9C8.64029 8.35971 9.09449 8 10 8H13.5L13.5 13.5H10C9.09449 13.5 8.64029 13.8597 8 14.5M10.25 3.75C10.25 4.99264 9.24264 6 8 6C6.75736 6 5.75 4.99264 5.75 3.75C5.75 2.50736 6.75736 1.5 8 1.5C9.24264 1.5 10.25 2.50736 10.25 3.75Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgCurate;
