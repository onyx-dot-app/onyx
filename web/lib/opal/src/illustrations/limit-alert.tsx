import type { IconProps } from "@opal/types";
const SvgLimitAlert = ({ size, ...props }: IconProps) => (
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
      d="M15 82.5C15 78.3579 18.3579 75 22.5 75L97.5 75C101.642 75 105 78.3579 105 82.5V90C105 94.1421 101.642 97.5 97.5 97.5L22.5 97.5C18.3579 97.5 15 94.1421 15 90V82.5Z"
      fill="#FBEAE4"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M93.75 86.25H78.75"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M67.5 86.2499H26.25"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M15 48.75C15 44.6079 18.3579 41.25 22.5 41.25L52.5 41.25C56.6421 41.25 60 44.6079 60 48.75L60 56.25C60 60.3921 56.6421 63.75 52.5 63.75H22.5C18.3579 63.75 15 60.3921 15 56.25L15 48.75Z"
      fill="#F0F0F0"
    />
    <path
      d="M45 52.5H26.25M52.5 63.75H22.5C18.3579 63.75 15 60.3921 15 56.25L15 48.75C15 44.6079 18.3579 41.25 22.5 41.25L52.5 41.25C56.6421 41.25 60 44.6079 60 48.75L60 56.25C60 60.3921 56.6421 63.75 52.5 63.75Z"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M86.25 41.25C81.0723 41.25 76.875 45.4473 76.875 50.625L76.875 63.75L86.25 63.75L95.625 63.75V50.625C95.625 45.4473 91.4277 41.25 86.25 41.25Z"
      fill="#FBEAE4"
    />
    <path
      d="M76.875 63.75L76.875 50.625C76.875 45.4473 81.0723 41.25 86.25 41.25C91.4277 41.25 95.625 45.4473 95.625 50.625V63.75M76.875 63.75L86.25 63.75M76.875 63.75L73.125 63.75M95.625 63.75H99.375M95.625 63.75L86.25 63.75M86.25 52.5V63.75M76.875 33.75L71.25 28.125M95.625 33.75L101.25 28.125M86.25 30L86.25 22.5"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgLimitAlert;
