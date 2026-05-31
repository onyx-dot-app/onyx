import Svg, { Path } from "react-native-svg";

// NOTE: every icon below is copied verbatim (viewBox + path `d`) from the matching
// web Opal source in `web/lib/opal/src/icons/*`, so the mobile glyph is pixel-identical.

// Icons ported 1:1 from the web Opal icon set (web/lib/opal/src/icons/*) so the
// mobile UI matches the web exactly — same viewBox + path data. Stroke uses `color`
// (pass a resolved theme token via useToken). Add more here as later phases need
// them (edit-big → New Session, search-menu → Search, settings → Admin,
// onyx-octagon → More Agents, folder → Projects, more-horizontal, plus, …).

export interface IconProps {
  size?: number;
  color?: string;
  strokeWidth?: number;
}

// web: lib/opal/src/icons/sidebar.tsx — sidebar open/collapse toggle
export function SidebarIcon({
  size = 16,
  color = "#000",
  strokeWidth = 1.5,
}: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <Path
        d="M6 2V14M3.33333 2H12.6667C13.403 2 14 2.59695 14 3.33333V12.6667C14 13.403 13.403 14 12.6667 14H3.33333C2.59695 14 2 13.403 2 12.6667V3.33333C2 2.59695 2.59695 2 3.33333 2Z"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

// web: lib/opal/src/icons/chevron-down.tsx
export function ChevronDownIcon({
  size = 16,
  color = "#000",
  strokeWidth = 1.5,
}: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <Path
        d="M4 6L8 10L12 6"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

// web: lib/opal/src/icons/arrow-up.tsx — send button (idle / has text)
export function ArrowUpIcon({
  size = 16,
  color = "#000",
  strokeWidth = 1.5,
}: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <Path
        d="M8 2.6665V13.3335M8 2.6665L4 6.6665M8 2.6665L12 6.6665"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

// web: lib/opal/src/icons/stop.tsx — send button while streaming.
// Web fills the square with --background-tint-00 and strokes currentColor; on a
// filled primary button we render a solid rounded square in the icon color.
export function StopIcon({
  size = 16,
  color = "#000",
  strokeWidth = 1.5,
}: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <Path
        d="M12 4H4V12H12V4Z"
        fill={color}
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

// web: lib/opal/src/icons/cpu.tsx — generic/fallback model-provider icon
export function CpuIcon({
  size = 16,
  color = "#000",
  strokeWidth = 1.5,
}: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <Path
        d="M6.09091 1V2.90909M9.90909 1V2.90909M6.09091 13.0909V15M9.90909 13.0909V15M13.0909 6.09091H15M13.0909 9.27273H15M1 6.09091H2.90909M1 9.27273H2.90909M4.18182 2.90909H11.8182C12.5211 2.90909 13.0909 3.47891 13.0909 4.18182V11.8182C13.0909 12.5211 12.5211 13.0909 11.8182 13.0909H4.18182C3.47891 13.0909 2.90909 12.5211 2.90909 11.8182V4.18182C2.90909 3.47891 3.47891 2.90909 4.18182 2.90909ZM6 6H10V10H6V6Z"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

// web: lib/opal/src/icons/paperclip.tsx — attach files
export function PaperclipIcon({
  size = 16,
  color = "#000",
  strokeWidth = 1.5,
}: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <Path
        d="M12.0924 3.99814L12.0924 10.6626C12.0924 11.724 11.6707 12.742 10.9202 13.4926C10.1696 14.2431 9.15163 14.6648 8.09018 14.6648C7.02872 14.6648 6.01074 14.2431 5.26018 13.4926C4.50961 12.742 4.08795 11.724 4.08795 10.6626L4.08795 3.99814C4.08795 3.2905 4.36906 2.61184 4.86944 2.11147C5.36981 1.6111 6.04847 1.32999 6.7561 1.32999C7.46374 1.32999 8.14239 1.61109 8.64277 2.11147C9.14314 2.61184 9.42425 3.2905 9.42425 3.99814L9.41954 10.6673C9.41954 11.0211 9.27898 11.3604 9.0288 11.6106C8.77861 11.8608 8.43928 12.0013 8.08546 12.0013C7.73164 12.0013 7.39232 11.8608 7.14213 11.6106C6.89194 11.3604 6.75139 11.0211 6.75139 10.6673L6.7561 4.66753"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

// web: lib/opal/src/icons/check.tsx — selected model row
export function CheckIcon({
  size = 16,
  color = "#000",
  strokeWidth = 1.5,
}: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <Path
        d="M13.5 4.5L6 12L2.5 8.5"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

// web: lib/opal/src/icons/chevron-right.tsx — collapsible group toggle
export function ChevronRightIcon({
  size = 16,
  color = "#000",
  strokeWidth = 1.5,
}: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <Path
        d="M6 12L10 8L6 4"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

// web: lib/opal/src/icons/edit-big.tsx — "New Session" / new chat
export function EditBigIcon({
  size = 16,
  color = "#000",
  strokeWidth = 1.5,
}: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <Path
        d="M8 2.5H4C3.17157 2.5 2.5 3.17157 2.5 4V12C2.5 12.8284 3.17157 13.5 4 13.5H12C12.8284 13.5 13.5 12.8284 13.5 12V8M6 10V8.26485C6 8.08682 6.0707 7.91617 6.19654 7.79028L11.5938 2.3931C12.1179 1.86897 12.9677 1.86897 13.4918 2.3931L13.6069 2.50823C14.131 3.03236 14.131 3.88213 13.6069 4.40626L8.20971 9.80345C8.08389 9.92934 7.91317 10 7.73521 10H6Z"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

// web: lib/opal/src/icons/search.tsx — model search box
export function SearchIcon({
  size = 16,
  color = "#000",
  strokeWidth = 1.5,
}: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <Path
        d="M14 14L11.1 11.1M12.6667 7.33333C12.6667 10.2789 10.2789 12.6667 7.33333 12.6667C4.38781 12.6667 2 10.2789 2 7.33333C2 4.38781 4.38781 2 7.33333 2C10.2789 2 12.6667 4.38781 12.6667 7.33333Z"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

// web: lib/opal/src/icons/file-text.tsx — non-image attachment glyph (viewBox 16×20)
export function FileTextIcon({
  size = 16,
  color = "#000",
  strokeWidth = 1.5,
}: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 16 20" fill="none">
      <Path
        d="M9.66634 1.6665H2.99967C2.55765 1.6665 2.13372 1.8421 1.82116 2.15466C1.5086 2.46722 1.33301 2.89114 1.33301 3.33317V16.6665C1.33301 17.1085 1.5086 17.5325 1.82116 17.845C2.13372 18.1576 2.55765 18.3332 2.99967 18.3332H12.9997C13.4417 18.3332 13.8656 18.1576 14.1782 17.845C14.4907 17.5325 14.6663 17.1085 14.6663 16.6665V6.6665M9.66634 1.6665L14.6663 6.6665M9.66634 1.6665L9.66634 6.6665L14.6663 6.6665M11.333 10.8332H4.66634M11.333 14.1665H4.66634M6.33301 7.49984H4.66634"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

// web: lib/opal/src/icons/image.tsx — image attachment / "Photos" picker row
export function ImageIcon({
  size = 16,
  color = "#000",
  strokeWidth = 1.5,
}: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <Path
        d="M11 14L6.06066 9.06072C5.47487 8.47498 4.52513 8.47498 3.93934 9.06072L2 11M2 3.49998C2 2.67156 2.67157 2 3.5 2H12.5C13.3285 2 14 2.67156 14 3.49998V12.4999C14 13.3283 13.3285 13.9998 12.5 13.9998H3.5C2.67157 13.9998 2 13.3283 2 12.4999V3.49998ZM9.875 7.62492C10.7034 7.62492 11.375 6.95338 11.375 6.12494C11.375 5.29653 10.7034 4.62496 9.875 4.62496C9.04655 4.62496 8.375 5.29653 8.375 6.12494C8.375 6.95338 9.04655 7.62492 9.875 7.62492Z"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
      />
    </Svg>
  );
}

// web: lib/opal/src/icons/x.tsx — remove/close (viewBox 28, heavier stroke)
export function XIcon({
  size = 16,
  color = "#000",
  strokeWidth = 2.5,
}: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 28 28" fill="none">
      <Path
        d="M21 7L7 21M7 7L21 21"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinejoin="round"
      />
    </Svg>
  );
}

// web: lib/opal/src/icons/loader.tsx — spinner arc (viewBox 15); rotate via <Spinner/>
export function LoaderIcon({
  size = 16,
  color = "#000",
  strokeWidth = 1.5,
}: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 15 15" fill="none">
      <Path
        d="M7.41667 14.0833C3.73477 14.0833 0.75 11.0986 0.75 7.41667C0.75 3.73477 3.73477 0.75 7.41667 0.75C11.0986 0.75 14.0833 3.73477 14.0833 7.41667"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

// web: lib/opal/src/icons/upload-square.tsx — "Upload File" picker row
export function UploadSquareIcon({
  size = 16,
  color = "#000",
  strokeWidth = 1.5,
}: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <Path
        d="M11 14H12.6667C13.3929 14 14 13.3929 14 12.6667V3.33333C14 2.60711 13.3929 2 12.6667 2H3.33333C2.60711 2 2 2.60711 2 3.33333V12.6667C2 13.3929 2.60711 14 3.33333 14H5M10.6666 8.16667L7.99998 5.5M7.99998 5.5L5.33331 8.16667M7.99998 5.5V14"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

// web: lib/opal/src/icons/more-horizontal.tsx — "All Recent Files" row
export function MoreHorizontalIcon({
  size = 16,
  color = "#000",
  strokeWidth = 1.5,
}: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <Path
        d="M8 8.75C8.41421 8.75 8.75 8.41421 8.75 8C8.75 7.58579 8.41421 7.25 8 7.25C7.58579 7.25 7.25 7.58579 7.25 8C7.25 8.41421 7.58579 8.75 8 8.75Z"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Path
        d="M12.75 8.75C13.1642 8.75 13.5 8.41421 13.5 8C13.5 7.58579 13.1642 7.25 12.75 7.25C12.3358 7.25 12 7.58579 12 8C12 8.41421 12.3358 8.75 12.75 8.75Z"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Path
        d="M3.25 8.75C3.66421 8.75 4 8.41421 4 8C4 7.58579 3.66421 7.25 3.25 7.25C2.83579 7.25 2.5 7.58579 2.5 8C2.5 8.41421 2.83579 8.75 3.25 8.75Z"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}
