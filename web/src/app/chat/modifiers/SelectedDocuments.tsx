import { BasicClickable } from "@/components/BasicClickable";
import { DanswerDocument } from "@/lib/search/interfaces";
import { FiBook } from "react-icons/fi";

export function SelectedDocuments({
  selectedDocuments,
}: {
  selectedDocuments: DanswerDocument[];
}) {
  if (selectedDocuments.length === 0) {
    return null;
  }

  return (
    <BasicClickable>
      <div className="flex text-xs max-w-md overflow-hidden">
        <FiBook className="my-auto mr-1" />{" "}
        <div className="w-fit whitespace-nowrap">
          Chatting with {selectedDocuments.length} Selected Documents
        </div>
      </div>
    </BasicClickable>
  );
}
