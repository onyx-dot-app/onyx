import type { IconProps } from "@opal/types/icons";

const SvgSun = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <g clipPath="url(#clip0_2458_12738)">
      <path
        d="M8 1L8 2.5M8 13.5V15M3.04909 3.04909L4.11091 4.11091M11.8891 11.8891L12.9509 12.9509M1 8L2.5 8M13.5 8L15 8M3.04909 12.9509L4.11091 11.8891M11.8891 4.11091L12.9509 3.04909M11 8C11 9.65685 9.65685 11 8 11C6.34315 11 5 9.65685 5 8C5 6.34315 6.34315 5 8 5C9.65685 5 11 6.34315 11 8Z"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
    <defs>
      <clipPath id="clip0_2458_12738">
        <rect width={16} height={16} fill="white" />
      </clipPath>
    </defs>
  </svg>
);
export default SvgSun;
