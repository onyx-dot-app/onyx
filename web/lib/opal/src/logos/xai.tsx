import type { IconProps } from "@opal/types";
const SvgXai = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 52 52"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M7.48081 19.8457L26.0886 47H34.3597L15.7498 19.8457H7.48081ZM15.7434 34.9273L7.47021 47H15.7477L19.8811 40.9648L15.7434 34.9273ZM36.2516 5L21.951 25.8679L26.0886 31.9075L44.5291 5H36.2516ZM37.7495 17.9126V47H44.5291V8.0198L37.7495 17.9126Z"
      fill="var(--text-05)"
    />
  </svg>
);
export default SvgXai;
