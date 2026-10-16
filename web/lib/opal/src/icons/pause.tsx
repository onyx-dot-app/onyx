import type { IconProps } from "@opal/types";

const SvgPause = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <rect
      x={3.33333}
      y={2.66667}
      width={2.66667}
      height={10.6667}
      rx={0.666667}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <rect
      x={10}
      y={2.66667}
      width={2.66667}
      height={10.6667}
      rx={0.666667}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgPause;
