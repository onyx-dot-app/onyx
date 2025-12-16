import type { IconProps } from "../index";

const SvgMenu = ({ size, ...props }: IconProps) => (
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
      d="M26.5 9H5.5M5.5 23H26.5M26.5 16H5.5"
      strokeWidth={2}
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgMenu;
