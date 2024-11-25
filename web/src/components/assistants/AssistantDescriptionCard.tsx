import { Persona } from "@/app/admin/assistants/interfaces";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import React from "react";

export function DisplayAssistantCard({
  selectedPersona,
}: {
  selectedPersona: Persona;
}) {
  return (
    <div className="p-4 bg-white/90 backdrop-blur-sm rounded-lg shadow-md border border-border/50 max-w-md w-full mx-auto transition-all duration-300 ease-in-out hover:shadow-lg">
      <div className="flex items-center mb-3">
        <AssistantIcon
          disableToolip
          size="medium"
          assistant={selectedPersona}
        />
        <h2 className="ml-3 text-xl font-semibold text-text-900">
          {selectedPersona.name}
        </h2>
      </div>
      <p className="text-sm text-text-600 mb-3 leading-relaxed">
        {selectedPersona.description}
      </p>
      {selectedPersona.tools.length > 0 ||
      selectedPersona.llm_relevance_filter ||
      selectedPersona.llm_filter_extraction ? (
        <div className="space-y-2">
          <h3 className="text-base font-medium text-text-900">Capabilities:</h3>
          <ul className="space-y-.5">
            {/* display all tools */}
            {selectedPersona.tools.map((tool, index) => (
              <li
                key={index}
                className="flex items-center text-sm text-text-700"
              >
                <span className="mr-2 text-text-500 opacity-70">•</span>{" "}
                {tool.display_name}
              </li>
            ))}
            {/* Built in capabilities */}
            {selectedPersona.llm_relevance_filter && (
              <li className="flex items-center text-sm text-text-700">
                <span className="mr-2 text-text-500 opacity-70">•</span>{" "}
                Advanced Relevance Filtering
              </li>
            )}
            {selectedPersona.llm_filter_extraction && (
              <li className="flex items-center text-sm text-text-700">
                <span className="mr-2 text-text-500 opacity-70">•</span> Smart
                Information Extraction
              </li>
            )}
          </ul>
        </div>
      ) : (
        <p className="text-sm text-text-600 italic">
          No specific capabilities listed for this assistant.
        </p>
      )}
    </div>
  );
}
