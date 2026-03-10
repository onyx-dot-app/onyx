import type { IconProps } from "@opal/types";

const SvgHandle = ({ size = 16, ...props }: IconProps) => (
  <svg
    width={Math.round((size * 3) / 17)}
    height={size}
    viewBox="0 0 3 17"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M0.5 0.5V16.5M2.5 0.5V16.5"
      stroke="currentColor"
      strokeLinecap="round"
    />
  </svg>
);

export default SvgHandle;
