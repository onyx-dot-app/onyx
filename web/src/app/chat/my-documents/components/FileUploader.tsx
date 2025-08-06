import React, { useState } from 'react';
import { FileUploadProgress } from '../../../../components/FileUploadProgress';
import { Button } from '../../../../components/ui/button';

interface FileUploaderProps {
  folderId?: number;
  onFilesUploaded?: (files: any[]) => void;
}

export function FileUploader({ folderId, onFilesUploaded }: FileUploaderProps) {
  const [isUploading, setIsUploading] = useState(false);
  const [uploadedFileIds, setUploadedFileIds] = useState<number[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  
  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    if (!event.target.files?.length) return;
    
    setIsUploading(true);
    setUploadError(null);
    
    const formData = new FormData();
    Array.from(event.target.files).forEach((file) => {
      formData.append('files', file);
    });
    
    if (folderId !== undefined) {
      formData.append('folder_id', folderId.toString());
    }
    
    try {
      const response = await fetch('/api/user/file/upload', {
        method: 'POST',
        body: formData,
      });
      
      if (!response.ok) {
        throw new Error(`Upload failed: ${response.statusText}`);
      }
      
      const data = await response.json();
      const fileIds = data.map((file: any) => file.id);
      setUploadedFileIds(fileIds);
      
      // Notify parent component if callback is provided
      if (onFilesUploaded) {
        onFilesUploaded(data);
      }
    } catch (error) {
      console.error('Error uploading files:', error);
      setUploadError(error instanceof Error ? error.message : 'Upload failed');
    } finally {
      setIsUploading(false);
    }
  };
  
  const handleUploadComplete = () => {
    // Reset the upload state after files are ready
    setUploadedFileIds([]);
  };
  
  return (
    <div className="space-y-4">
      <div className="flex items-center">
        <input
          id="file-upload"
          type="file"
          multiple
          onChange={handleFileUpload}
          disabled={isUploading}
          className="hidden"
        />
        <label htmlFor="file-upload" className="cursor-pointer">
          <Button 
            type="button" 
            disabled={isUploading}
            variant="outline"
          >
            {isUploading ? 'Uploading...' : 'Upload Files'}
          </Button>
        </label>
      </div>
      
      {uploadError && (
        <div className="text-red-500 text-sm">{uploadError}</div>
      )}
      
      {uploadedFileIds.length > 0 && (
        <FileUploadProgress 
          fileIds={uploadedFileIds} 
          onComplete={handleUploadComplete} 
          className="mt-4"
        />
      )}
    </div>
  );
}
