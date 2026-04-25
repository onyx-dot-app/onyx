import type { IconProps } from "@opal/types";
const SvgExa = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 52 52"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      fillRule="evenodd"
      clipRule="evenodd"
      d="M9.58008 5H42.4164V8.13433L28.403 26L42.4164 43.8657V47H9.58008V5ZM26.2047 23.1092L37.5922 8.13433H14.8173L26.2047 23.1092ZM13.2744 11.887V24.4329H22.8147L13.2744 11.887ZM22.8147 27.5671H13.2744V40.113L22.8147 27.5671ZM14.8173 43.8657L26.2047 28.8908L37.5922 43.8657H14.8173Z"
      fill="#1F40ED"
    />
  </svg>
);
export default SvgExa;
