--- backend/danswer/connectors/README.md
+++ backend/danswer/connectors/README.md
@@ -0,0 +1 @@
+To add a new connector, create a new python file in this directory and implement the necessary logic to pull in tickets from a specified Jira Service Management project.

--- backend/danswer/connectors/__init__.py
+++ backend/danswer/connectors/__init__.py
@@ -0,0 +1 @@
+from .jira_service_management import JiraServiceManagementConnector

--- backend/danswer/connectors/jira_service_management.py
+++ backend/danswer/connectors/jira_service_management.py
@@ -0,0 +1,15 @@
+import requests
+
+class JiraServiceManagementConnector:
+    def __init__(self, project_id):
+        self.project_id = project_id
+        self.api_url = "https://your-jira-instance.atlassian.net/rest/api/2"
+        self.auth = ("your-username", "your-password")
+
+    def get_tickets(self):
+        response = requests.get(
+            f"{self.api_url}/search?jql=project={self.project_id}", auth=self.auth
+        )
+        return response.json()["issues"]
