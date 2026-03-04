import type { IconProps } from "@opal/types";

const SvgGripVertical = ({ size = 16, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <circle cx="6" cy="3.5" r="1" fill="currentColor" />
    <circle cx="10" cy="3.5" r="1" fill="currentColor" />
    <circle cx="6" cy="8" r="1" fill="currentColor" />
    <circle cx="10" cy="8" r="1" fill="currentColor" />
    <circle cx="6" cy="12.5" r="1" fill="currentColor" />
    <circle cx="10" cy="12.5" r="1" fill="currentColor" />
  </svg>
);

export default SvgGripVertical;
