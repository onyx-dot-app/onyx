from onyx.configs.constants import DocumentSource


def source_to_github_img_link(source: DocumentSource) -> str | None:
    # TODO: store these images somewhere better
    if source == DocumentSource.WEB.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/backend/slackbot_images/Web.png"
    if source == DocumentSource.FILE.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/backend/slackbot_images/File.png"
    if source == DocumentSource.GOOGLE_SITES.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/GoogleSites.png"
    if source == DocumentSource.SLACK.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/Slack.png"
    if source == DocumentSource.GMAIL.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/Gmail.png"
    if source == DocumentSource.GOOGLE_DRIVE.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/GoogleDrive.png"
    if source == DocumentSource.GITHUB.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/Github.png"
    if source == DocumentSource.GITLAB.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/Gitlab.png"
    if source == DocumentSource.CONFLUENCE.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/backend/slackbot_images/Confluence.png"
    if source == DocumentSource.JIRA.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/backend/slackbot_images/Jira.png"
    if source == DocumentSource.NOTION.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/Notion.png"
    if source == DocumentSource.ZENDESK.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/backend/slackbot_images/Zendesk.png"
    if source == DocumentSource.GONG.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/Gong.png"
    if source == DocumentSource.LINEAR.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/Linear.png"
    if source == DocumentSource.PRODUCTBOARD.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/Productboard.webp"
    if source == DocumentSource.SLAB.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/SlabLogo.png"
    if source == DocumentSource.ZULIP.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/Zulip.png"
    if source == DocumentSource.GURU.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/backend/slackbot_images/Guru.png"
    if source == DocumentSource.HUBSPOT.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/HubSpot.png"
    if source == DocumentSource.DOCUMENT360.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/Document360.png"
    if source == DocumentSource.BOOKSTACK.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/Bookstack.png"
    if source == DocumentSource.OUTLINE.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/Outline.png"
    if source == DocumentSource.LOOPIO.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/Loopio.png"
    if source == DocumentSource.SHAREPOINT.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/Sharepoint.png"
    if source == DocumentSource.REQUESTTRACKER.value:
        # just use file icon for now
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/backend/slackbot_images/File.png"
    if source == DocumentSource.INGESTION_API.value:
        return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/backend/slackbot_images/File.png"

    return "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/backend/slackbot_images/File.png"
