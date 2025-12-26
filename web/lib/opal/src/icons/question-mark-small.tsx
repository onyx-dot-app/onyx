import type { IconProps } from "@opal/types";
const SvgQuestionMarkSmall = ({ size, ...props }: IconProps) => (
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
      d="M6.06 5.99995C6.21673 5.5544 6.5261 5.17869 6.9333 4.93937C7.3405 4.70006 7.81926 4.61258 8.28478 4.69243C8.7503 4.77228 9.17254 5.0143 9.47672 5.37564C9.78089 5.73697 9.94737 6.1943 9.94666 6.66662C9.94666 7.99995 7.94666 8.66662 7.94666 8.66662M8 11.3333H8.00666"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgQuestionMarkSmall;
