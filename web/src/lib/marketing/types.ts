export interface Campaign {
  id: string;
  name: string;
  description: string;
  status: 'draft' | 'active' | 'paused' | 'completed';
  textContent?: string;
  imageContent?: string;
  createdAt: Date;
  updatedAt: Date;
}

export interface CreateCampaignRequest {
  name: string;
  description: string;
  status: 'draft' | 'active' | 'paused' | 'completed';
}

export interface UpdateCampaignRequest {
  name?: string;
  description?: string;
  status?: 'draft' | 'active' | 'paused' | 'completed';
  textContent?: string;
  imageContent?: string;
}

export interface GenerateContentRequest {
  prompt: string;
  type: 'text' | 'image';
}

export interface GenerateContentResponse {
  content: string;
  type: 'text' | 'image';
}
