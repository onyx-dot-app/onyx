"use client";

import { useState, useEffect } from "react";
import { ApiKeyForm } from "./ApiKeyForm";
import { Modal } from "../Modal";
import { Divider, Text } from "@tremor/react";

export async function checkApiKey() {
  const response = await fetch("/api/manage/admin/genai-api-key/validate");
  if (!response.ok && (response.status === 404 || response.status === 400)) {
    const jsonResponse = await response.json();
    return jsonResponse.detail;
  }
  return null;
}

export const ApiKeyModal = () => {
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    checkApiKey().then((error) => {
      if (error) {
        setErrorMsg(error);
      }
    });
  }, []);

  if (!errorMsg) {
    return null;
  }

  return (
    <Modal
      title="LLM Key Setup"
      className="max-w-4xl"
      onOutsideClick={() => setErrorMsg(null)}
    >
      <div>
        <div>
          <div className="mb-2.5 text-base">
            Please provide a valid OpenAI API key below in order to start using
            Danswer Search or Danswer Chat.
            <br />
            <br />
            Or if you&apos;d rather look around first,{" "}
            <strong
              onClick={() => setErrorMsg(null)}
              className="text-link cursor-pointer"
            >
              skip this step
            </strong>
            .
          </div>

          <Divider />

          <ApiKeyForm
            handleResponse={(response) => {
              if (response.ok) {
                setErrorMsg(null);
              }
            }}
          />
        </div>
      </div>
    </Modal>
  );
};
