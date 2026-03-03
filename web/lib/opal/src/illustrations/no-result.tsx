import type { IconProps } from "@opal/types";
const SvgNoResult = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 120 120"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path d="M91.875 45H28.125L11.25 112.5H108.75L91.875 45Z" fill="white" />
    <path
      d="M26.25 45L50.0345 23.8582C52.8762 21.3323 56.4381 20.0693 60 20.0693C63.5619 20.0693 67.1238 21.3323 69.9655 23.8582L93.75 45H26.25Z"
      fill="#E6E6E6"
    />
    <path
      d="M60 7.5V20.0693M60 20.0693C56.4381 20.0693 52.8762 21.3323 50.0345 23.8582L26.25 45H93.75L69.9655 23.8582C67.1238 21.3323 63.5619 20.0693 60 20.0693Z"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M43.125 99.375L33.75 90M60 91.875V78.75M76.875 99.375L86.25 90"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgNoResult;
