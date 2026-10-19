import type { IconProps } from "@opal/types";

const SvgFileBroadcast = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 18 18"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M6.1875 2.25003H2.625C1.808 2.25003 1.125 2.93303 1.125 3.75003L1.125 14.25C1.125 15.067 1.808 15.75 2.625 15.75L9.37125 15.75C10.1883 15.75 10.8713 15.067 10.8713 14.25L10.8713 6.94128M6.1875 2.25003L10.8713 6.94128M6.1875 2.25003V6.94128H10.8713M10.3069 2.25L13.216 5.15914C13.6379 5.5811 13.875 6.15339 13.875 6.75013V13.875C13.875 14.5212 13.737 15.2081 13.4392 15.7538M16.4391 15.7538C16.737 15.2081 16.875 14.5213 16.875 13.8751L16.875 7.02481C16.875 5.53418 16.2833 4.10451 15.23 3.04982L14.4301 2.25003"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgFileBroadcast;
