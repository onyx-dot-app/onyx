"use client";

import React, { useEffect, useState } from 'react';
import Text from '@/components/ui/text';
import { Button } from '@/components/ui/button';
import { usePopup } from '@/components/admin/connectors/Popup';
import { Textarea } from '@/components/ui/textarea';

const Prompts = () => {
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const { popup, setPopup } = usePopup();

  const fetchPrompts = async () => {
    try {
      const response = await fetch('/api/prompts');
      if (!response.ok) {
        throw new Error('Failed to fetch prompts');
      }
      const data = await response.json();
      setPrompts(data);
    } catch (error) {
      console.error('Error fetching prompts:', error);
      setPopup({
        message: 'Failed to load prompts',
        type: 'error'
      });
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchPrompts();
  }, []); // Empty dependency array means this only runs once on mount

  const handleSave = async () => {
    setIsSaving(true);
    try {
      // The backend expects a PromptUpdate object with a root property that is a dictionary of strings
      const response = await fetch('/api/prompts', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(prompts), // Send the dictionary directly
      });

      if (!response.ok) {
        throw new Error('Failed to save prompts');
      }

      setPopup({
        message: 'Prompts saved successfully',
        type: 'success'
      });
    } catch (error) {
      console.error('Error saving prompts:', error);
      setPopup({
        message: 'Failed to save prompts',
        type: 'error'
      });
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return <div>Loading prompts...</div>;
  }

  return (
    <div>
      {popup}
      <div className="flex justify-between items-center mb-4">
        <Button 
          onClick={handleSave}
          disabled={isSaving}
          className="ml-auto"
        >
          {isSaving ? 'Saving...' : 'Save Changes'}
        </Button>
      </div>
      <div className="space-y-6">
        {Object.entries(prompts).map(([key, prompt]) => (
          <div key={key} className="space-y-2">
            <h3 className="font-semibold text-lg">{key}</h3>
            <Textarea
              className="min-h-[500px] font-mono"
              value={prompt}
              onChange={(e) => setPrompts({ ...prompts, [key]: e.target.value })}
            />
          </div>
        ))}
      </div>
    </div>
  );
};

export default Prompts; 