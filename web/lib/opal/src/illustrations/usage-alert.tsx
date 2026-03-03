import type { IconProps } from "@opal/types";
const SvgUsageAlert = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 120 120"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M15 90C15 85.8578 18.3579 82.5 22.5 82.5L60 82.5C64.1421 82.5 67.5 85.8578 67.5 90L67.5 97.5C67.5 101.642 64.1421 105 60 105H22.5C18.3579 105 15 101.642 15 97.5L15 90Z"
      fill="#F0F0F0"
    />
    <path
      d="M15 22.5C15 18.3579 18.3579 15 22.5 15H45C49.1421 15 52.5 18.3579 52.5 22.5L52.5 29.9999C52.5 34.1421 49.1421 37.4999 45 37.4999H22.5C18.3579 37.4999 15 34.1421 15 29.9999V22.5Z"
      fill="#F0F0F0"
    />
    <path
      d="M52.5 93.75H26.25M37.5 26.25H26.25M22.5 15H45C49.1421 15 52.5 18.3579 52.5 22.5L52.5 29.9999C52.5 34.1421 49.1421 37.4999 45 37.4999H22.5C18.3579 37.4999 15 34.1421 15 29.9999V22.5C15 18.3579 18.3579 15 22.5 15ZM60 105H22.5C18.3579 105 15 101.642 15 97.5L15 90C15 85.8578 18.3579 82.5 22.5 82.5L60 82.5C64.1421 82.5 67.5 85.8578 67.5 90L67.5 97.5C67.5 101.642 64.1421 105 60 105Z"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M78.75 60H71.25M90 37.5V30M103.125 50.625H110.625M99.375 41.25L105 35.625M82.5 71.25L22.5 71.25C18.3579 71.25 15 67.8922 15 63.75V56.25C15 52.1079 18.3579 48.75 22.5 48.75L82.5 48.75C86.6421 48.75 90 52.1079 90 56.25V63.75C90 67.8922 86.6421 71.25 82.5 71.25Z"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M60 60H26.25"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgUsageAlert;
