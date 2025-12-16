import type { IconProps } from "@opal/types";

const SvgEyeClosed = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 10"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M1 1.5C1 1.5 1.69706 2.89413 3 4.22328M15 1.5C15 1.5 14.3029 2.89413 13 4.22328M3 4.22328C3.78612 5.02522 4.7928 5.80351 6 6.23767M3 4.22328L1 6.22328M6 6.23767C6.61544 6.45901 7.28299 6.59091 8 6.59091C8.71701 6.59091 9.38456 6.45901 10 6.23767M6 6.23767L5 8.99908M10 6.23767C11.2072 5.80351 12.2139 5.02522 13 4.22328M10 6.23767L11 8.99908M13 4.22328L15 6.22328"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgEyeClosed;
