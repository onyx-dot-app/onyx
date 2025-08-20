import { FiImage, FiSearch } from "react-icons/fi";
import { Persona } from "../admin/assistants/interfaces";
import { SEARCH_TOOL_ID } from "../chat/components/tools/constants";

export function AssistantTools({
  assistant,
  list,
  hovered,
}: {
  assistant: Persona;
  list?: boolean;
  hovered?: boolean;
}) {
  return (
    <div className="relative text-xs overflow-x-hidden flex text-subtle">
      <span
        className={`${assistant.tools.length > 0 && "py-1"}  ${
          !list ? "font-semibold" : "text-subtle text-sm"
        }`}
      >
        Tools:
      </span>{" "}
      {assistant.tools.length == 0 ? (
        <p className="ml-1">None</p>
      ) : (
        <div className="ml-1 flex flex-wrap gap-1">
          {assistant.tools.map((tool, ind) => {
            if (tool.name === SEARCH_TOOL_ID) {
              return (
                <div
                  key={ind}
                  className={`
                    px-1.5
                    py-1
                    rounded-lg 
                    border
                    border-border 
                    w-fit 
                    flex
                    items-center
                    ${list ? "bg-background-125" : "bg-background-100"}`}
                >
                  <div className="flex gap-x-1">
                    <FiSearch key={ind} className="ml-1 h-3 w-3 my-auto" />
                    Search
                  </div>
                </div>
              );
            } else if (tool.name === "ImageGenerationTool") {
              return (
                <div
                  key={ind}
                  className={`
                    px-1.5
                    py-1
                    rounded-lg 
                    border
                    border-border 
                    w-fit 
                    flex
                    ${list ? "bg-background-125" : "bg-background-100"}`}
                >
                  <div className="flex items-center gap-x-1">
                    <FiImage
                      key={ind}
                      className="ml-1 my-auto h-3 w-3 my-auto"
                    />
                    Image Generation
                  </div>
                </div>
              );
            } else {
              return (
                <div
                  key={ind}
                  className={`
                  px-1.5
                  py-1
                  rounded-lg 
                  border
                  border-border 
                  w-fit 
                  flex
                  items-center
                  ${
                    hovered
                      ? "bg-background-300"
                      : list
                        ? "bg-background-125"
                        : "bg-background-100"
                  }`}
                >
                  <div className="flex gap-x-1">{tool.name}</div>
                </div>
              );
            }
          })}
        </div>
      )}
    </div>
  );
}
