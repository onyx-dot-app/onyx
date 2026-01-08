import type { IconProps } from "@opal/types";
const SvgSlidersSmall = ({ size, ...props }: IconProps) => (
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
      d="M6 11V8.75M6 6.75V5M6 6.75H4.75M6 6.75H7.25M10 11V9.25M10 9.25H8.75M10 9.25H11.25M10 7.25V5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgSlidersSmall;
