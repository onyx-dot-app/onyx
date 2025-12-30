import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgFileText, SvgMaximize2 } from "@opal/icons";
export interface AttachmentsProps {
  fileName: string;
  open?: () => void;
}

export default function Attachments({ fileName, open }: AttachmentsProps) {
  return (
    <div className="flex items-center border bg-background-tint-00 rounded-12 p-1 gap-1">
      <div className="p-2 bg-background-tint-01 rounded-08">
        <SvgFileText className="w-[1.25rem] h-[1.25rem] stroke-text-02" />
      </div>
      <div className="flex flex-col px-2">
        <Text as="p" secondaryAction>
          {fileName}
        </Text>
        <Text as="p" secondaryBody text03>
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
