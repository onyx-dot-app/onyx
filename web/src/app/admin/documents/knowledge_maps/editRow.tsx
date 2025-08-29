import { useRouter } from "next/navigation";
import { FiEdit } from "react-icons/fi";

export const EditRow = ({ knowledgeMap }: { knowledgeMap: any }) => {
  const router = useRouter();
  return (
    <div className="relative flex">
      <div
        className={
          "text-emphasis font-medium my-auto p-1 hover:bg-hover-light flex cursor-pointer select-none" +
          (knowledgeMap.is_up_to_date ? " cursor-pointer" : " cursor-default")
        }
        onClick={() => {
          router.push(`/admin/documents/knowledge_maps/${knowledgeMap.id}`);
        }}
      >
        <FiEdit className="text-emphasis mr-1 my-auto" />
        {knowledgeMap.name}
      </div>
    </div>
  );
};
