import type { IconProps } from "@opal/types";

const SvgCircle = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <circle cx="8" cy="8" r="6" strokeWidth={1.5} />
  </svg>
);
export default SvgCircle;
