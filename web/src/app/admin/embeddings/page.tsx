"use client";

import { EmbeddingFormProvider } from "@/components/context/EmbeddingContext";
import EmbeddingSidebar from "../../../sections/sidebar/UpsertEmbeddingSidebar";
import EmbeddingForm from "./pages/EmbeddingFormPage";

export default function EmbeddingWrapper() {
  return (
    <EmbeddingFormProvider>
      <div className="flex justify-center w-full h-full">
        <EmbeddingSidebar />
        <div className="mt-12 w-full max-w-5xl mx-auto">
          <EmbeddingForm />
        </div>
      </div>
    </EmbeddingFormProvider>
  );
}
