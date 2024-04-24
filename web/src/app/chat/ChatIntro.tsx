import { getSourceMetadataForSources, listSourceMetadata } from "@/lib/sources";
import { ValidSources } from "@/lib/types";
import Image from "next/image";
import { Persona } from "../admin/assistants/interfaces";
import { Divider } from "@tremor/react";
import { FiBookmark, FiCpu, FiInfo, FiX, FiZoomIn } from "react-icons/fi";
import { HoverPopup } from "@/components/HoverPopup";
import { Modal } from "@/components/Modal";
import { useState } from "react";
import { FaRobot } from "react-icons/fa";
import { SourceMetadata } from "@/lib/search/interfaces";

const MAX_PERSONAS_TO_DISPLAY = 4;

function HelperItemDisplay({
  title,
  description,
  model,
}: {
  title: string;
  description: string;
  model: string;
}) {
  return (
    <div className="cursor-pointer hover:bg-hover-light border border-border rounded py-2 px-4">
      <div className="text-emphasis font-bold text-lg flex">{title}</div>
      <div className="text-sm">{description}</div>
      <div className="text-sm">Using model <i>{model}</i></div>
    </div>
  );
}

function AllPersonaOptionDisplay({
  availablePersonas,
  defaultModel,
  handlePersonaSelect,
  handleClose,
}: {
  availablePersonas: Persona[];
  defaultModel: string;
  handlePersonaSelect: (persona: Persona) => void;
  handleClose: () => void;
}) {
  return (
    <Modal onOutsideClick={handleClose}>
      <div>
        <div className="flex w-full border-b border-border mb-4 pb-4">
          <h2 className="text-xl text-strong font-bold flex">
            <div className="p-1 bg-ai rounded-lg h-fit my-auto mr-2">
              <div className="text-inverted">
                <FiCpu size={16} className="my-auto mx-auto" />
              </div>
            </div>
            All Available Assistants
          </h2>

          <div
            onClick={handleClose}
            className="ml-auto p-1 rounded hover:bg-hover"
          >
            <FiX size={18} />
          </div>
        </div>
        <div className="flex flex-col gap-y-4 max-h-96 overflow-y-auto pb-4 px-2">
          {availablePersonas.map((persona) => (
            <div
              key={persona.id}
              onClick={() => {
                handleClose();
                handlePersonaSelect(persona);
              }}
            >
              <HelperItemDisplay
                title={persona.name}
                description={persona.description}
                model={persona.llm_model_version_override || defaultModel}
              />
            </div>
          ))}
        </div>
      </div>
    </Modal>
  );
}

export function ChatIntro({
  availableSources,
  availablePersonas,
  defaultModel,
  selectedPersona,
  handlePersonaSelect,
}: {
  availableSources: ValidSources[];
  availablePersonas: Persona[];
  defaultModel: string;
  selectedPersona?: Persona;
  handlePersonaSelect: (persona: Persona) => void;
}) {
  const [isAllPersonaOptionVisible, setIsAllPersonaOptionVisible] =
    useState(false);

  const availableSourceMetadata = getSourceMetadataForSources(availableSources);
  return (
    <>
      {isAllPersonaOptionVisible && (
        <AllPersonaOptionDisplay
          handleClose={() => setIsAllPersonaOptionVisible(false)}
          availablePersonas={availablePersonas}
          defaultModel={defaultModel}
          handlePersonaSelect={handlePersonaSelect}
        />
      )}
      <div className="flex justify-center items-center h-full">
        {selectedPersona ? (
          <div className="w-message-xs 2xl:w-message-sm 3xl:w-message">
            <div className="flex">
              <div className="mx-auto">
                <div className="m-auto h-[80px] w-[80px]">
                  <Image
                    src="/logo.png"
                    alt="Logo"
                    width="1419"
                    height="1520"
                  />
                </div>
                <div className="m-auto text-3xl font-bold text-strong mt-4 w-fit">
                  {selectedPersona?.name || "How can I help you today?"}
                </div>
                {selectedPersona && (
                  <>
                    <div className="mt-1">{selectedPersona.description}</div>
                    <div>Using model <i>{selectedPersona.llm_model_version_override || defaultModel}</i></div>
                  </>
                )}
              </div>
            </div>

            {selectedPersona && selectedPersona.num_chunks !== 0 && (
              <>
                <Divider />
                <div>
                  {selectedPersona.document_sets.length > 0 && (
                    <div className="mt-2">
                      <p className="font-bold mb-1 mt-4 text-emphasis">
                        Knowledge Sets:{" "}
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {selectedPersona.document_sets.map((documentSet) => (
                          <div key={documentSet.id} className="w-fit">
                            <HoverPopup
                              mainContent={
                                <span className="flex w-fit p-1 rounded border border-border text-xs font-medium cursor-default">
                                  <div className="mr-1 my-auto">
                                    <FiBookmark />
                                  </div>
                                  {documentSet.name}
                                </span>
                              }
                              popupContent={
                                <div className="flex py-1 w-96">
                                  <FiInfo className="my-auto mr-2" />
                                  <div className="text-sm">
                                    {documentSet.description}
                                  </div>
                                </div>
                              }
                              direction="top"
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {availableSources.length > 0 && (
                    <div className="mt-2">
                      <p className="font-bold mb-1 mt-4 text-emphasis">
                        Connected Sources:{" "}
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {availableSourceMetadata.map((sourceMetadata) => (
                          <span
                            key={sourceMetadata.internalName}
                            className="flex w-fit p-1 rounded border border-border text-xs font-medium cursor-default"
                          >
                            <div className="mr-1 my-auto">
                              {sourceMetadata.icon({})}
                            </div>
                            <div className="my-auto">
                              {sourceMetadata.displayName}
                            </div>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        ) : (
          <div className="px-12 w-searchbar-xs 2xl:w-searchbar-sm 3xl:w-searchbar">
            <div className="mx-auto">
              <div className="m-auto h-[80px] w-[80px]">
                <Image src="/logo.png" alt="Logo" width="1419" height="1520" />
              </div>
            </div>

            <div className="mt-2">
              <p className="font-bold text-xl mb-1 mt-4 text-emphasis text-center">
                Which assistant do you want to chat with today?{" "}
              </p>
              <p className="text-sm text-center">
                Or ask a question immediately to use the{" "}
                <b>{availablePersonas[0]?.name}</b> assistant.
              </p>
              <div className="flex flex-col gap-y-4 mt-8">
                {availablePersonas
                  .slice(0, MAX_PERSONAS_TO_DISPLAY)
                  .map((persona) => (
                    <div
                      key={persona.id}
                      onClick={() => handlePersonaSelect(persona)}
                    >
                      <HelperItemDisplay
                        title={persona.name}
                        description={persona.description}
                        model={persona.llm_model_version_override || defaultModel}
                      />
                    </div>
                  ))}
              </div>
              {availablePersonas.length > MAX_PERSONAS_TO_DISPLAY && (
                <div className="mt-4 flex">
                  <div
                    onClick={() => setIsAllPersonaOptionVisible(true)}
                    className="text-sm flex mx-auto p-1 hover:bg-hover-light rounded cursor-default"
                  >
                    <FiZoomIn className="my-auto mr-1" /> See more
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
