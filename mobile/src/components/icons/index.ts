// ===========================================================================
// Icons barrel — curated Opal icon set, ported to React Native.
// ===========================================================================
//
// Onyx rule: ONLY curated icons (no icon-font libraries). Every icon here is a
// hand-port of its web counterpart in web/lib/opal/src/icons/. To add more,
// follow the port recipe documented at the top of `Icon.tsx`, then register the
// new `Svg*` component below.
// ===========================================================================

export {
  Icon,
  type IconProps,
  type IconRenderProps,
  type IconVariant,
} from "@/components/icons/Icon";

export { SvgX } from "@/components/icons/SvgX";
export { SvgCheck } from "@/components/icons/SvgCheck";
export { SvgChevronRight } from "@/components/icons/SvgChevronRight";
export { SvgChevronDown } from "@/components/icons/SvgChevronDown";
export { SvgPlus } from "@/components/icons/SvgPlus";
export { SvgSearch } from "@/components/icons/SvgSearch";
export { SvgSettings } from "@/components/icons/SvgSettings";
export { SvgArrowUp } from "@/components/icons/SvgArrowUp";
export { SvgArrowLeft } from "@/components/icons/SvgArrowLeft";
export { SvgTrash } from "@/components/icons/SvgTrash";
export { SvgCopy } from "@/components/icons/SvgCopy";
export { SvgMenu } from "@/components/icons/SvgMenu";
export { SvgUser } from "@/components/icons/SvgUser";
export { SvgLogOut } from "@/components/icons/SvgLogOut";

// Timeline / agent-message icon set (ported from web/lib/opal/src/icons).
export { SvgCircle } from "@/components/icons/SvgCircle";
export { SvgSearchMenu } from "@/components/icons/SvgSearchMenu";
export { SvgGlobe } from "@/components/icons/SvgGlobe";
export { SvgFileText } from "@/components/icons/SvgFileText";
export { SvgEditBig } from "@/components/icons/SvgEditBig";
export { SvgTerminal } from "@/components/icons/SvgTerminal";
export { SvgSparkle } from "@/components/icons/SvgSparkle";
export { SvgCheckCircle } from "@/components/icons/SvgCheckCircle";
export { SvgXCircle } from "@/components/icons/SvgXCircle";
export { SvgBookOpen } from "@/components/icons/SvgBookOpen";
export { SvgBranch } from "@/components/icons/SvgBranch";
export { SvgFold } from "@/components/icons/SvgFold";
export { SvgExpand } from "@/components/icons/SvgExpand";
export { SvgMaximize2 } from "@/components/icons/SvgMaximize2";
export { SvgStopCircle } from "@/components/icons/SvgStopCircle";
export { SvgXOctagon } from "@/components/icons/SvgXOctagon";
export { SvgArrowExchange } from "@/components/icons/SvgArrowExchange";
export { SvgExternalLink } from "@/components/icons/SvgExternalLink";
export { SvgDownload } from "@/components/icons/SvgDownload";
export { SvgImage } from "@/components/icons/SvgImage";

// Aliases — the Opal curated set has no dedicated glyph for these, so the
// closest curated icon stands in (documented at the source component).
export { SvgArrowUp as SvgSend } from "@/components/icons/SvgArrowUp";
