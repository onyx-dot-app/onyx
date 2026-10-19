import type { IconProps } from "@opal/types";
const SvgXOctagon = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <g clipPath="url(#clip0_16_2894)">
      <path
        d="M10 6.00004L5.99999 10M5.99999 6.00004L10 10M5.23999 1.33337H10.76L14.6667 5.24004V10.76L10.76 14.6667H5.23999L1.33333 10.76V5.24004L5.23999 1.33337Z"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
    <defs>
      <clipPath id="clip0_16_2894">
        <rect fill="white" />
      </clipPath>
    </defs>
  </svg>
);
export default SvgXOctagon;
