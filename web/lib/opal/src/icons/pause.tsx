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
      x={4}
      y={2.75}
      width={2.5}
      height={10.5}
      rx={0.5}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <rect
      x={9.5}
      y={2.75}
      width={2.5}
      height={10.5}
      rx={0.5}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgPause;
