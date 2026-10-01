import type { IconProps } from "@opal/types";

const SvgLoader = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    {/* A 3/4 ring: from the bottom, round through the left and top, to the
    right. Static and unsized; IconLoader spins and sizes it. */}
    <path
      d="M8 14.6667A6.66667 6.66667 0 1 1 14.6667 8"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgLoader;
