import type { IconProps } from "@opal/types";
const SvgNoAccess = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 120 120"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M18.75 22.5V105L60 105L101.25 105V22.5C101.25 18.3578 97.8921 15 93.75 15H60H26.25C22.1079 15 18.75 18.3578 18.75 22.5Z"
      fill="white"
    />
    <path
      d="M18.75 105V22.5C18.75 18.3578 22.1079 15 26.25 15H60M18.75 105L60 105M18.75 105L11.25 105M101.25 105V22.5C101.25 18.3578 97.8921 15 93.75 15H60M101.25 105L60 105M101.25 105H108.75M60 93.75V105M60 15V26.25"
      stroke="#CCCCCC"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M46.875 58.1249V50.625C46.875 43.3762 52.7512 37.5 60 37.5C67.2487 37.5 73.125 43.3762 73.125 50.625V58.125M46.875 58.1249L44.9999 58.1249C42.9289 58.125 41.25 59.8039 41.25 61.8749V78.75C41.25 80.821 42.9289 82.5 45 82.5L75 82.5C77.071 82.5 78.75 80.821 78.75 78.75V61.875C78.75 59.8039 77.071 58.125 75 58.125H73.125M46.875 58.1249L73.125 58.125M60 67.4999V73.1249"
      stroke="#A4A4A4"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgNoAccess;
