import { useState, useRef, useCallback } from "react";

export interface UseVoiceRecorderReturn {
  isRecording: boolean;
  isProcessing: boolean;
  error: string | null;
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<string | null>;
}

export function useVoiceRecorder(): UseVoiceRecorderReturn {
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const startRecording = useCallback(async () => {
    setError(null);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Use browser's preferred format
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      chunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to start recording";
      setError(message);
      throw err;
    }
  }, []);

  const stopRecording = useCallback(async (): Promise<string | null> => {
    const mediaRecorder = mediaRecorderRef.current;
    if (!mediaRecorder || mediaRecorder.state === "inactive") {
      return null;
    }

    return new Promise((resolve) => {
      mediaRecorder.onstop = async () => {
        setIsRecording(false);
        setIsProcessing(true);

        try {
          const audioBlob = new Blob(chunksRef.current, {
            type: mediaRecorder.mimeType || "audio/webm",
          });

          // Determine file extension from MIME type
          const mimeType = mediaRecorder.mimeType || "audio/webm";
          let extension = "webm";
          if (mimeType.includes("mp4") || mimeType.includes("m4a")) {
            extension = "m4a";
          } else if (mimeType.includes("ogg")) {
            extension = "ogg";
          }

          const formData = new FormData();
          formData.append("audio", audioBlob, `recording.${extension}`);

          const response = await fetch("/api/voice/transcribe", {
            method: "POST",
            body: formData,
          });

          if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || "Transcription failed");
          }

          const data = await response.json();
          setError(null);
          resolve(data.text);
        } catch (err) {
          const message =
            err instanceof Error ? err.message : "Transcription failed";
          setError(message);
          resolve(null);
        } finally {
          setIsProcessing(false);
          // Stop all tracks to release microphone
          mediaRecorder.stream.getTracks().forEach((track) => track.stop());
        }
      };

      mediaRecorder.stop();
    });
  }, []);

  return {
    isRecording,
    isProcessing,
    error,
    startRecording,
    stopRecording,
  };
}
