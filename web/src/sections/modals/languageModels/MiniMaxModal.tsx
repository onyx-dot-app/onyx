import { LLMProviderFormProps, LLMProviderName } from "@/lib/languageModels/types";
import { OpenAICompatibleModal } from "@/sections/modals/languageModels/OpenAICompatibleModal";

const MINIMAX_API_BASE = "https://api.minimax.io/v1";

export default function MiniMaxModal(props: LLMProviderFormProps) {
  return (
    <OpenAICompatibleModal
      {...props}
      providerName={LLMProviderName.MINIMAX}
      defaultApiBase={MINIMAX_API_BASE}
      description="Connect to MiniMax models through MiniMax's OpenAI-compatible endpoint."
    />
  );
}
