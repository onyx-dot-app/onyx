'use client';

import React, { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Plus } from 'lucide-react';
import { Campaign, CreateCampaignRequest, UpdateCampaignRequest } from '@/lib/marketing/types';
import {
  fetchCampaigns,
  createCampaign,
  updateCampaign,
  deleteCampaign,
} from '@/services/marketingService';
import CampaignList from '@/components/marketing/CampaignList';
import CreateCampaignModal from '@/components/marketing/CreateCampaignModal';
import EditCampaignModal from '@/components/marketing/EditCampaignModal';
import DeleteCampaignModal from '@/components/marketing/DeleteCampaignModal';
import ContentGenerationModal from '@/components/marketing/ContentGenerationModal';

export default function MarketingPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string>('');

  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [contentModalOpen, setContentModalOpen] = useState(false);
  
  const [selectedCampaign, setSelectedCampaign] = useState<Campaign | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    loadCampaigns();
  }, []);

  const loadCampaigns = async () => {
    try {
      setIsLoading(true);
      setError('');
      const data = await fetchCampaigns();
      setCampaigns(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load campaigns');
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateCampaign = async (data: CreateCampaignRequest) => {
    try {
      setIsCreating(true);
      const newCampaign = await createCampaign(data);
      setCampaigns(prev => [...prev, newCampaign]);
      setCreateModalOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create campaign');
    } finally {
      setIsCreating(false);
    }
  };

  const handleEditCampaign = (campaign: Campaign) => {
    setSelectedCampaign(campaign);
    setEditModalOpen(true);
  };

  const handleUpdateCampaign = async (id: string, data: UpdateCampaignRequest) => {
    try {
      setIsUpdating(true);
      const updatedCampaign = await updateCampaign(id, data);
      setCampaigns(prev => prev.map(c => c.id === id ? updatedCampaign : c));
      setEditModalOpen(false);
      setSelectedCampaign(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update campaign');
    } finally {
      setIsUpdating(false);
    }
  };

  const handleDeleteCampaign = (campaign: Campaign) => {
    setSelectedCampaign(campaign);
    setDeleteModalOpen(true);
  };

  const handleConfirmDelete = async (id: string) => {
    try {
      setIsDeleting(true);
      await deleteCampaign(id);
      setCampaigns(prev => prev.filter(c => c.id !== id));
      setDeleteModalOpen(false);
      setSelectedCampaign(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete campaign');
    } finally {
      setIsDeleting(false);
    }
  };

  const handleGenerateContent = (campaign: Campaign) => {
    setSelectedCampaign(campaign);
    setContentModalOpen(true);
  };

  const handleContentGenerated = async (id: string, content: string, type: 'text' | 'image') => {
    try {
      const updateData: UpdateCampaignRequest = {};
      if (type === 'text') {
        updateData.textContent = content;
      } else {
        updateData.imageContent = content;
      }
      
      const updatedCampaign = await updateCampaign(id, updateData);
      setCampaigns(prev => prev.map(c => c.id === id ? updatedCampaign : c));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save generated content');
    }
  };

  return (
    <div className="container mx-auto p-6 max-w-7xl">
      <div className="mb-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-3xl font-bold text-foreground">Marketing Campaigns</h1>
            <p className="text-muted-foreground mt-1">
              Create and manage your marketing campaigns with AI-powered content generation
            </p>
          </div>
          <Button onClick={() => setCreateModalOpen(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Create Campaign
          </Button>
        </div>

        {error && (
          <div className="p-4 bg-red-50 border border-red-200 rounded-md mb-4">
            <p className="text-sm text-red-600">{error}</p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setError('')}
              className="mt-2"
            >
              Dismiss
            </Button>
          </div>
        )}
      </div>

      <CampaignList
        campaigns={campaigns}
        onEdit={handleEditCampaign}
        onDelete={handleDeleteCampaign}
        onGenerateContent={handleGenerateContent}
        isLoading={isLoading}
      />

      <CreateCampaignModal
        onSubmit={handleCreateCampaign}
        trigger={<></>}
        open={createModalOpen}
        setOpen={setCreateModalOpen}
        isLoading={isCreating}
      />

      {selectedCampaign && (
        <>
          <EditCampaignModal
            campaign={selectedCampaign}
            onSubmit={handleUpdateCampaign}
            trigger={<></>}
            open={editModalOpen}
            setOpen={setEditModalOpen}
            isLoading={isUpdating}
          />

          <DeleteCampaignModal
            campaign={selectedCampaign}
            onConfirm={handleConfirmDelete}
            trigger={<></>}
            open={deleteModalOpen}
            setOpen={setDeleteModalOpen}
            isLoading={isDeleting}
          />

          <ContentGenerationModal
            campaign={selectedCampaign}
            onContentGenerated={handleContentGenerated}
            trigger={<></>}
            open={contentModalOpen}
            setOpen={setContentModalOpen}
          />
        </>
      )}
    </div>
  );
}
