"use client";

import type { LLMProviderFormProps } from "@/lib/languageModels/types";
import DecisionProviderModal from "@/sections/modals/languageModels/DecisionProviderModal";

export default function NaceModal(props: LLMProviderFormProps) {
  return <DecisionProviderModal {...props} providerName="nace" />;
}
