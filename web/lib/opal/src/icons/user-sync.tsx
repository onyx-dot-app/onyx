import type { IconProps } from "@opal/types";

const SvgUserSync = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 32 32"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M2 28C2 27.3333 2 26.6667 2 26C2 22.6863 4.68632 20 8.00003 20H14M22 17L19 20L29 19.9997M26 28L29 25L19 25M17.5 9.5C17.5 12.5376 15.0376 15 12 15C8.96243 15 6.5 12.5376 6.5 9.5C6.5 6.46243 8.96243 4 12 4C15.0376 4 17.5 6.46243 17.5 9.5Z"
      strokeWidth={2.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgUserSync;
