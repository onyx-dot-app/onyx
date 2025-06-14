# YouTube Connector

This connector allows Onyx to index and search through your YouTube videos and their metadata.

## Features

- OAuth2 authentication with YouTube API
- Indexes video titles, descriptions, and metadata
- Supports polling for new videos
- Captures video statistics (views, likes, comments)
- Links directly to videos in YouTube

## Setup

1. Create a project in the [Google Cloud Console](https://console.cloud.google.com/)
2. Enable the YouTube Data API v3
3. Create OAuth 2.0 credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Choose "Desktop app" as the application type
   - Download the client secrets file and save it as `client_secrets.json` in the connector directory

## Required Permissions

The connector requires the following OAuth scopes:

- `https://www.googleapis.com/auth/youtube.readonly` - For reading video data
- `https://www.googleapis.com/auth/youtube.force-ssl` - For accessing private videos

## Usage

1. Add the YouTube connector in Onyx
2. Authenticate with your YouTube account
3. The connector will start indexing your videos
4. Videos will be searchable in Onyx with their titles, descriptions, and metadata

## Data Indexed

For each video, the connector indexes:

- Title
- Description
- Publication date
- View count
- Like count
- Comment count
- Duration
- Channel information
- Direct link to the video

## Limitations

- Only videos from the authenticated user's channel are indexed
- Maximum of 50 videos per polling interval
- API quotas apply based on your Google Cloud project settings
