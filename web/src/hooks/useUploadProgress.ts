// web/src/hooks/useUploadProgress.ts
import { useState, useCallback } from 'react';

export interface UploadProgressState {
  isUploading: boolean;
  progress: number;
  stage: 'uploading' | 'processing' | 'indexing' | 'complete' | 'error';
  fileName: string;
  error?: string;
}

export interface FileUploadProgress {
  [fileName: string]: UploadProgressState;
}

export const useUploadProgress = () => {
  const [uploadProgress, setUploadProgress] = useState<FileUploadProgress>({});

  const updateProgress = useCallback((fileName: string, update: Partial<UploadProgressState>) => {
    setUploadProgress(prev => {
      const currentState = prev[fileName] || {
        isUploading: false,
        progress: 0,
        stage: 'uploading' as const,
        fileName,
        error: undefined
      };
      
      return {
        ...prev,
        [fileName]: {
          ...currentState,
          ...update,
          fileName // Ensure fileName is always set
        }
      };
    });
  }, []);

  const startUpload = useCallback((fileName: string) => {
    updateProgress(fileName, {
      isUploading: true,
      progress: 0,
      stage: 'uploading',
      fileName,
      error: undefined
    });
  }, [updateProgress]);

  const setFileProgress = useCallback((fileName: string, progress: number) => {
    updateProgress(fileName, { 
      progress, 
      stage: 'uploading',
      fileName 
    });
  }, [updateProgress]);

  const setProcessingStage = useCallback((fileName: string, stage: UploadProgressState['stage']) => {
    const progressMap = {
      'uploading': 25,
      'processing': 50,
      'indexing': 75,
      'complete': 100,
      'error': 0
    };
    
    updateProgress(fileName, { 
      stage, 
      progress: progressMap[stage],
      isUploading: stage !== 'complete' && stage !== 'error',
      fileName
    });
  }, [updateProgress]);

  const setError = useCallback((fileName: string, error: string) => {
    updateProgress(fileName, {
      isUploading: false,
      progress: 0,
      stage: 'error',
      fileName,
      error
    });
  }, [updateProgress]);

  const completeUpload = useCallback((fileName: string) => {
    updateProgress(fileName, {
      isUploading: false,
      progress: 100,
      stage: 'complete',
      fileName,
      error: undefined
    });
    
    // Auto-remove completed uploads after 3 seconds
    setTimeout(() => {
      setUploadProgress(prev => {
        const { [fileName]: removed, ...rest } = prev;
        return rest;
      });
    }, 3000);
  }, [updateProgress]);

  const removeProgress = useCallback((fileName: string) => {
    setUploadProgress(prev => {
      const { [fileName]: removed, ...rest } = prev;
      return rest;
    });
  }, []);

  return {
    uploadProgress,
    startUpload,
    setFileProgress,
    setProcessingStage,
    setError,
    completeUpload,
    removeProgress
  };
};
