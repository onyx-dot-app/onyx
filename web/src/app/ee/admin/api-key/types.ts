interface APIKey {
  api_key_id: number;
  api_key_display: string;
  api_key: string | null;
  api_key_name: string | null;
  user_id: string;
}

interface APIKeyArgs {
  name?: string;
}
