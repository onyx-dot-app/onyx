from enum import auto
from enum import StrEnum


class SourceType(StrEnum):
    GITHUB = auto()
    BITBUCKET = auto()
    CONFLUENCE = auto()
    GOOGLE_DRIVE = auto()
    SLACK = auto()
    DROPBOX = auto()
    JIRA = auto()
    ASANA = auto()
    TRELLO = auto()
    ZENDESK = auto()
    SALESFORCE = auto()
    NOTION = auto()
    AIRTABLE = auto()
    MONDAY = auto()
    FIGMA = auto()
    INTERCOM = auto()
    HUBSPOT = auto()
    BOX = auto()
    SHAREPOINT = auto()
    SERVICENOW = auto()
