"use client";

import { EmbeddingFormProvider } from "@/components/context/EmbeddingContext";
import EmbeddingSidebar from "../../../components/embedding/EmbeddingSidebar";
import EmbeddingForm from "./pages/EmbeddingFormPage";

export default function EmbeddingWrapper() {
  return (
    <EmbeddingFormProvider>
      <div
        className="flex justify-center w-full h-full bg-background"
        style={{
          ["--background-input-background" as any]: "#FAFAFA",
          ["--background" as any]: "#FAFAFA",
          ["--background-chatbar-sidebar" as any]: "#F0F0F1",
        }}
      >
        <EmbeddingSidebar />
        <div className="mt-12 w-full max-w-5xl mx-auto">
          <EmbeddingForm />
        </div>
      </div>
    </EmbeddingFormProvider>
  );
}
