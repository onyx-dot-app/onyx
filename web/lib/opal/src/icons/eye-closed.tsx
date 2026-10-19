import type { IconProps } from "@opal/types";
const SvgEyeClosed = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M10 10.2377C9.38456 10.459 8.71701 10.5909 8 10.5909C7.28299 10.5909 6.61544 10.459 6 10.2377C4.7928 9.80351 3.78612 9.02522 3 8.22328C1.69706 6.89413 1 5.5 1 5.5M3 8.22328L1 10.2233M6 10.2377L5 12.9991M15 5.5C15 5.5 14.3029 6.89413 13 8.22328C12.2139 9.02522 11.2072 9.80351 10 10.2377M10 10.2377L11 12.9991M13 8.22328L15 10.2233"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgEyeClosed;
