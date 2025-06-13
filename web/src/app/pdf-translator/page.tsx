'use client';

import { FileUpload } from '@/components/admin/connectors/FileUpload';
import { ThreeDotsLoader } from '@/components/Loading';
import { UserDropdown } from '@/components/UserDropdown';
import { Formik } from 'formik';
import { useState } from 'react';
import * as Yup from 'yup';

interface ProcessedResult {
  filename: string;
  downloadUrl: string;
}

export default function PDFTranslatorPage() {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [result, setResult] = useState<ProcessedResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleProcess = async (file: File) => {
    setIsProcessing(true);
    setError(null);
    setResult(null);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch('/api/pdf-translator/process', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to process PDF');
      }

      const blob = await response.blob();
      const downloadUrl = URL.createObjectURL(blob);
      
      setResult({
        filename: `translated_${file.name}`,
        downloadUrl,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleFileSelect = (files: File[]) => {
    setSelectedFiles(files);
    if (files.length > 0) {
      handleProcess(files[0]);
    }
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-start bg-background-50 relative">
      <div className="absolute top-6 right-8 z-50">
        <UserDropdown />
      </div>
      <div className="w-full">
        <div className="max-w-6xl mx-auto px-8 py-8 text-center">
          <h1 className="text-4xl font-bold text-foreground mb-3">PDF Translation</h1>
        </div>
        <Formik
          initialValues={{}}
          validationSchema={Yup.object().shape({})}
          onSubmit={() => {}}
        >
        <div className="space-y-6 p-8">
            <div className="w-full mt-16">
            <div className="w-full border border-border rounded-xl p-8 bg-white shadow-sm flex flex-col items-center">
                <FileUpload
                selectedFiles={selectedFiles}
                setSelectedFiles={handleFileSelect}
                accept=".pdf,application/pdf"
                message="Upload your PDF"
                />
                {selectedFiles.length > 0 && (
                <div className="mt-2">
                    <p className="text-sm text-muted-foreground">
                    Selected: {selectedFiles[0].name}
                    </p>
                </div>
                )}
            </div>
            </div>

            {isProcessing && (
            <div className="flex justify-center">
                <ThreeDotsLoader />
            </div>
            )}

            {error && (
            <div className="max-w-6xl mx-auto px-8 border border-red-200 bg-red-50 text-red-700 p-6 rounded-xl">
                <p className="font-medium text-lg mb-2">Error</p>
                <p>{error}</p>
            </div>
            )}

            {result && (
            <div className="w-screen border-t border-border bg-white shadow-sm">
                <div className="w-full h-[calc(100vh-180px)] px-8">
                <iframe
                    src={result.downloadUrl}
                    className="w-full h-full"
                    title="Translated PDF Preview"
                />
                </div>
            </div>
            )}
        </div>
        </Formik>
      </div>
    </div>
  );
}
