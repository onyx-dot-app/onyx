# This is a group that we use to store all the users that we found in Confluence
# Instead of setting a page to public, we just add this group so that the page
# is only accessible to users who have confluence accounts.
ALL_CONF_EMAILS_GROUP_NAME = "All_Confluence_Users_Found_By_Onyx"

# JSON-RPC permission category that maps to "view this space" on
# Confluence Server / DC < 9.1.
VIEWSPACE_PERMISSION_TYPE = "VIEWSPACE"

# Field values from the Confluence DC 9.1+ space-permissions REST API.
# Response shape: list of {operation: {targetType, operationKey},
#                          subject:   {type, name|userKey},
#                          spaceKey, spaceId}
# Documented in CONFSERVER-78176 and the Confluence DC 9.1 release notes.
SPACE_PERMISSION_TARGET_TYPE_SPACE = "space"
SPACE_PERMISSION_OPERATION_READ = "read"
SPACE_PERMISSION_SUBJECT_TYPE_USER = "user"
SPACE_PERMISSION_SUBJECT_TYPE_GROUP = "group"

REQUEST_PAGINATION_LIMIT = 5000
