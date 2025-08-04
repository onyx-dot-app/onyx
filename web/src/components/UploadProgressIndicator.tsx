// web/src/components/UploadProgressIndicator.tsx
import React from 'react';

// Define the interfaces directly in this file since they're not exported from the hook
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

interface UploadProgressIndicatorProps {
  fileName: string;
  progress: UploadProgressState;
  onRemove?: (fileName: string) => void;
}

const stageLabels = {
  uploading: 'Uploading...',
  processing: 'Processing file...',
  indexing: 'Indexing for search...',
  complete: 'Ready to use!',
  error: 'Upload failed'
};

const stageColors = {
  uploading: 'bg-blue-500',
  processing: 'bg-yellow-500',
  indexing: 'bg-purple-500',
  complete: 'bg-green-500',
  error: 'bg-red-500'
};

export const UploadProgressIndicator: React.FC<UploadProgressIndicatorProps> = ({
  fileName,
  progress,
  onRemove
}) => {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm mb-2">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center space-x-2">
          <div className="text-sm font-medium text-gray-900 truncate max-w-xs">
            {fileName}
          </div>
          {progress.stage === 'complete' && (
            <svg className="w-4 h-4 text-green-500" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
            </svg>
          )}
          {progress.stage === 'error' && (
            <svg className="w-4 h-4 text-red-500" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
            </svg>
          )}
        </div>
        {onRemove && (progress.stage === 'complete' || progress.stage === 'error') && (
          <button
            onClick={() => onRemove(fileName)}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
            </svg>
          </button>
        )}
      </div>
      
      <div className="space-y-2">
        <div className="flex items-center justify-between text-sm">
          <span className={`font-medium ${progress.stage === 'error' ? 'text-red-600' : 'text-gray-700'}`}>
            {stageLabels[progress.stage]}
          </span>
          <span className="text-gray-500">{progress.progress}%</span>
        </div>
        
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div
            className={`h-2 rounded-full transition-all duration-300 ${stageColors[progress.stage]}`}
            style={{ width: `${progress.progress}%` }}
          />
        </div>
        
        {progress.error && (
          <div className="text-xs text-red-600 mt-1">
            {progress.error}
          </div>
        )}
      </div>
    </div>
  );
};

interface UploadProgressListProps {
  uploadProgress: FileUploadProgress;
  onRemove?: (fileName: string) => void;
}

export const UploadProgressList: React.FC<UploadProgressListProps> = ({
  uploadProgress,
  onRemove
}) => {
  const progressEntries = Object.entries(uploadProgress);
  
  if (progressEntries.length === 0) {
    return null;
  }

  return (
    <div className="fixed bottom-4 right-4 max-w-sm space-y-2 z-50">
      {progressEntries.map(([fileName, progress]) => (
        <UploadProgressIndicator
          key={fileName}
          fileName={fileName}
          progress={progress}
          onRemove={onRemove}
        />
      ))}
    </div>
  );
};
