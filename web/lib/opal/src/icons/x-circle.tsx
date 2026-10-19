import type { IconProps } from "@opal/types";
const SvgXCircle = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <g clipPath="url(#clip0_16_2868)">
      <path
        d="M10 6.00004L5.99999 10M5.99999 6.00004L10 10M14.6667 8.00004C14.6667 11.6819 11.6819 14.6667 7.99999 14.6667C4.3181 14.6667 1.33333 11.6819 1.33333 8.00004C1.33333 4.31814 4.3181 1.33337 7.99999 1.33337C11.6819 1.33337 14.6667 4.31814 14.6667 8.00004Z"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
    <defs>
      <clipPath id="clip0_16_2868">
        <rect fill="white" />
      </clipPath>
    </defs>
  </svg>
);
export default SvgXCircle;
