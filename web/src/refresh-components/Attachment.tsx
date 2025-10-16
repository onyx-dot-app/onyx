import SvgFileText from "@/icons/file-text";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgMaximize2 from "@/icons/maximize-2";

export interface AttachmentsProps {
  fileName: string;
  open?: () => void;
}

export default function Attachments({ fileName, open }: AttachmentsProps) {
  return (
    <div className="flex items-center border bg-background-tint-00 rounded-12 p-spacing-inline gap-spacing-inline">
      <div className="p-spacing-interline bg-background-tint-01 rounded-08">
        <SvgFileText className="w-[1.25rem] h-[1.25rem] stroke-text-02" />
      </div>
      <div className="flex flex-col px-spacing-interline">
        <Text secondaryAction>{fileName}</Text>
        <Text secondaryBody text03>
          Document
        </Text>
      </div>

      {open && (
        <IconButton
          aria-label="Expand document"
          onClick={open}
          icon={SvgMaximize2}
          internal
        />
      )}
    </div>
  );
}
