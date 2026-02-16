import type { IconProps } from "@opal/types";

const SvgKeystroke = ({ size, ...props }: IconProps) => (
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
      d="M12 4V9C12 9.55228 11.5523 10 11 10H5M5 10L6.5 8.5M5 10L6.5 11.5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgKeystroke;
