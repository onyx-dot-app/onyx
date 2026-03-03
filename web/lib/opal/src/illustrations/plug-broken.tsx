import type { IconProps } from "@opal/types";
const SvgPlugBroken = ({ size, ...props }: IconProps) => (
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
      d="M31.875 78.75L24.375 71.25M50.625 78.75L58.125 71.25M41.25 73.125V63.75"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M97.5 30H90H71.25H63.75V43.125C63.75 52.4448 71.3052 60 80.625 60C89.9448 60 97.5 52.4448 97.5 43.125V30Z"
      fill="#E6E6E6"
    />
    <path
      d="M50.625 90H95.625C99.7671 90 103.125 93.3579 103.125 97.5C103.125 101.642 99.7671 105 95.625 105H88.125C83.9829 105 80.625 101.642 80.625 97.5V60M31.875 90H16.875M90 30V18.75M90 30H97.5M90 30H71.25M97.5 30V43.125C97.5 52.4448 89.9448 60 80.625 60M97.5 30H103.125M63.75 30V43.125C63.75 52.4448 71.3052 60 80.625 60M63.75 30H71.25M63.75 30H58.125M71.25 30V18.75"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgPlugBroken;
