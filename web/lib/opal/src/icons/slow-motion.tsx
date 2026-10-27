import type { IconProps } from "@opal/types";
const SvgSlowMotion = ({ size, ...props }: IconProps) => (
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
      d="M13.1404 12.2453C11.9176 13.7243 10.0689 14.6666 7.99999 14.6666C6.70212 14.6666 5.49086 14.2958 4.46643 13.6542M14.4826 9.56239C14.6029 9.06124 14.6667 8.53805 14.6667 7.99998C14.6667 4.83386 12.4596 2.18324 9.5 1.50274M6.5 1.50274C5.76902 1.67081 5.08395 1.95907 4.46669 2.3456M2.3456 4.46669C1.95908 5.08395 1.67082 5.76902 1.50275 6.5M1.50276 9.5C1.67083 10.231 1.95909 10.916 2.34561 11.5333M6.66666 5.33331L10.6667 7.99997L6.66666 10.6666V5.33331Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgSlowMotion;
