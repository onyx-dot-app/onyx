import type { IconProps } from "@opal/types";
const SvgBracketCurly = ({ size, ...props }: IconProps) => (
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
      d="M5 2.00002C3.89543 2.00002 3 2.89545 3 4.00002V5.92966C3 6.59836 2.6658 7.22283 2.1094 7.59376L1.5 8.00002L2.1094 8.40629C2.6658 8.77722 3 9.40169 3 10.0704V12C3 13.1046 3.89543 14 5 14M11 14C12.1046 14 13 13.1046 13 12V10.0704C13 9.40167 13.3342 8.7772 13.8906 8.40627L14.5 8.00002L13.8906 7.59373C13.3342 7.2228 13 6.59835 13 5.92965V4C13 2.89543 12.1046 2 11 2"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgBracketCurly;
