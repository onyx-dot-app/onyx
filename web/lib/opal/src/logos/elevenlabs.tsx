import type { IconProps } from "@opal/types";
const SvgElevenLabs = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 52 52"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M30.6667 3.29004H40V48.7123H30.6667V3.29004Z"
      fill="var(--text-05)"
    />
    <path d="M12 3.29004H21.3333V48.7123H12V3.29004Z" fill="var(--text-05)" />
  </svg>
);
export default SvgElevenLabs;
