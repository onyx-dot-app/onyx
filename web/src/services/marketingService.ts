import { Campaign, CreateCampaignRequest, UpdateCampaignRequest } from "@/lib/marketing/types";

const MOCK_CAMPAIGNS: Campaign[] = [
  {
    id: "1",
    name: "Summer Sale Campaign",
    description: "Promote summer products with special discounts",
    status: "active",
    textContent: "Get ready for summer with our amazing deals!",
    imageContent: "",
    createdAt: new Date("2024-06-01"),
    updatedAt: new Date("2024-06-01"),
  },
  {
    id: "2", 
    name: "Product Launch",
    description: "Launch campaign for new product line",
    status: "draft",
    createdAt: new Date("2024-06-10"),
    updatedAt: new Date("2024-06-10"),
  },
];

let campaigns = [...MOCK_CAMPAIGNS];

export async function fetchCampaigns(): Promise<Campaign[]> {
  await new Promise(resolve => setTimeout(resolve, 500));
  return [...campaigns];
}

export async function createCampaign(data: CreateCampaignRequest): Promise<Campaign> {
  await new Promise(resolve => setTimeout(resolve, 500));
  
  const newCampaign: Campaign = {
    id: Date.now().toString(),
    name: data.name,
    description: data.description,
    status: data.status,
    createdAt: new Date(),
    updatedAt: new Date(),
  };
  
  campaigns.push(newCampaign);
  return newCampaign;
}

export async function updateCampaign(id: string, data: UpdateCampaignRequest): Promise<Campaign> {
  await new Promise(resolve => setTimeout(resolve, 500));
  
  const campaignIndex = campaigns.findIndex(c => c.id === id);
  if (campaignIndex === -1) {
    throw new Error("Campaign not found");
  }
  
  campaigns[campaignIndex] = {
    ...campaigns[campaignIndex],
    ...data,
    updatedAt: new Date(),
  };
  
  return campaigns[campaignIndex];
}

export async function deleteCampaign(id: string): Promise<void> {
  await new Promise(resolve => setTimeout(resolve, 500));
  
  const campaignIndex = campaigns.findIndex(c => c.id === id);
  if (campaignIndex === -1) {
    throw new Error("Campaign not found");
  }
  
  campaigns.splice(campaignIndex, 1);
}

export async function getCampaign(id: string): Promise<Campaign> {
  await new Promise(resolve => setTimeout(resolve, 500));
  
  const campaign = campaigns.find(c => c.id === id);
  if (!campaign) {
    throw new Error("Campaign not found");
  }
  
  return campaign;
}
