import type { IconProps } from "@opal/types";

const SvgStarOff = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <g clipPath="url(#clip0_5622_63664)">
      <path
        d="M1 1L5.56196 5.56196M15 15L5.56196 5.56196M5.56196 5.56196L1.33333 6.18004L4.66666 9.42671L3.88 14.0134L8 11.8467L12.12 14.0134L11.7267 11.72M12.1405 8.64051L14.6667 6.18004L10.06 5.50671L8 1.33337L6.95349 3.45349"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
    <defs>
      <clipPath id="clip0_5622_63664">
        <rect width={16} height={16} fill="white" />
      </clipPath>
    </defs>
  </svg>
);

export default SvgStarOff;
