import type { IconProps } from "@opal/types";
const SvgEyeOff = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <g clipPath="url(#clip0_139_1482)">
      <path
        d="M11.78 11.78C10.6922 12.6092 9.36761 13.0685 8 13.0909C3.54545 13.0909 1 8 1 8C1.79157 6.52484 2.88945 5.23602 4.22 4.22M11.78 11.78L9.34909 9.34909M11.78 11.78L15 15M4.22 4.22L1 1M4.22 4.22L6.65091 6.65091M6.66364 3.06182C7.10167 2.95929 7.55013 2.90803 8 2.90909C12.4545 2.90909 15 8 15 8C14.6137 8.72266 14.153 9.40301 13.6255 10.03M9.34909 9.34909L6.65091 6.65091M9.34909 9.34909C8.99954 9.72422 8.49873 9.94737 7.98606 9.95641C6.922 9.97519 6.02481 9.078 6.04358 8.01394C6.05263 7.50127 6.27578 7.00046 6.65091 6.65091"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
    <defs>
      <clipPath id="clip0_139_1482">
        <rect fill="white" />
      </clipPath>
    </defs>
  </svg>
);
export default SvgEyeOff;
