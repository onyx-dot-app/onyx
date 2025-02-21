import time
from collections.abc import Iterator
from datetime import datetime
from typing import Dict

import asana  # type: ignore

from onyx.utils.logger import setup_logger

logger = setup_logger()


# https://github.com/Asana/python-asana/tree/master?tab=readme-ov-file#documentation-for-api-endpoints
class AsanaTask:
    def __init__(
        self,
        id: str,
        title: str,
        text: str,
        link: str,
        last_modified: datetime,
        project_gid: str,
        project_name: str,
    ) -> None:
        self.id = id
        self.title = title
        self.text = text
        self.link = link
        self.last_modified = last_modified
        self.project_gid = project_gid
        self.project_name = project_name

    def __str__(self) -> str:
        return f"ID: {self.id}\nTitle: {self.title}\nLast modified: {self.last_modified}\nText: {self.text}"


class AsanaAPI:
    def __init__(
        self, api_token: str, workspace_gid: str, team_gid: str | None
    ) -> None:
        self._user = None  # type: ignore
        self.workspace_gid = workspace_gid
        self.team_gid = team_gid

        self.configuration = asana.Configuration()
        self.api_client = asana.ApiClient(self.configuration)
        self.tasks_api = asana.TasksApi(self.api_client)
        self.stories_api = asana.StoriesApi(self.api_client)
        self.users_api = asana.UsersApi(self.api_client)
        self.project_api = asana.ProjectsApi(self.api_client)
        self.workspaces_api = asana.WorkspacesApi(self.api_client)

        self.api_error_count = 0
        self.configuration.access_token = api_token
        self.task_count = 0

    def get_tasks(
        self, project_gids: list[str] | None, start_date: str
    ) -> Iterator[AsanaTask]:
        """Get all tasks from the projects with the given gids that were modified since the given date.
        If project_gids is None, get all tasks from all projects in the workspace."""
        logger.info("Starting to fetch Asana projects")
        projects = self.project_api.get_projects(
            opts={
                "workspace": self.workspace_gid,
                "opt_fields": "gid,name,archived,modified_at",
            }
        )
        start_seconds = int(time.mktime(datetime.now().timetuple()))
        projects_list = []
        project_count = 0
        for project_info in projects:
            project_gid = project_info["gid"]
            if project_gids is None or project_gid in project_gids:
                projects_list.append(project_gid)
            else:
                logger.debug(
                    f"Skipping project: {project_gid} - not in accepted project_gids"
                )
            project_count += 1
            if project_count % 100 == 0:
                logger.info(f"Processed {project_count} projects")

        logger.info(f"Found {len(projects_list)} projects to process")
        for project_gid in projects_list:
            for task in self._get_tasks_for_project(
                project_gid, start_date, start_seconds
            ):
                yield task
        logger.info(f"Completed fetching {self.task_count} tasks from Asana")
        if self.api_error_count > 0:
            logger.warning(
                f"Encountered {self.api_error_count} API errors during task fetching"
            )

    def _get_tasks_for_project(
        self, project_gid: str, start_date: str, start_seconds: int
    ) -> Iterator[AsanaTask]:
        project = self.project_api.get_project(project_gid, opts={})
        if project["archived"]:
            logger.info(f"Skipping archived project: {project['name']} ({project_gid})")
            yield from []
        if not project["team"] or not project["team"]["gid"]:
            logger.info(
                f"Skipping project without a team: {project['name']} ({project_gid})"
            )
            yield from []
        if project["privacy_setting"] == "private":
            if self.team_gid and project["team"]["gid"] != self.team_gid:
                logger.info(
                    f"Skipping private project not in configured team: {project['name']} ({project_gid})"
                )
                yield from []
            else:
                logger.info(
                    f"Processing private project in configured team: {project['name']} ({project_gid})"
                )

        simple_start_date = start_date.split(".")[0].split("+")[0]
        logger.info(
            f"Fetching tasks modified since {simple_start_date} for project: {project['name']} ({project_gid})"
        )

        opts = {
            "opt_fields": "name,memberships,memberships.project,completed_at,completed_by,created_at,"
            "created_by,custom_fields,dependencies,due_at,due_on,external,html_notes,liked,likes,"
            "modified_at,notes,num_hearts,parent,projects,resource_subtype,resource_type,start_on,"
            "workspace,permalink_url",
            "modified_since": start_date,
        }
        tasks_from_api = self.tasks_api.get_tasks_for_project(project_gid, opts)
        for data in tasks_from_api:
            self.task_count += 1
            if self.task_count % 10 == 0:
                end_seconds = time.mktime(datetime.now().timetuple())
                runtime_seconds = end_seconds - start_seconds
                if runtime_seconds > 0:
                    logger.info(
                        f"Processed {self.task_count} tasks in {runtime_seconds:.0f} seconds "
                        f"({self.task_count / runtime_seconds:.2f} tasks/second)"
                    )

            logger.debug(f"Processing Asana task: {data['name']}")

            text = self._construct_task_text(data)

            try:
                text += self._fetch_and_add_comments(data["gid"])

                last_modified_date = self.format_date(data["modified_at"])
                text += f"Last modified: {last_modified_date}\n"

                task = AsanaTask(
                    id=data["gid"],
                    title=data["name"],
                    text=text,
                    link=data["permalink_url"],
                    last_modified=datetime.fromisoformat(data["modified_at"]),
                    project_gid=project_gid,
                    project_name=project["name"],
                )
                yield task
            except Exception:
                logger.error(
                    f"Error processing task {data['gid']} in project {project_gid}",
                    exc_info=True,
                )
                self.api_error_count += 1

    def _construct_task_text(self, data: Dict) -> str:
        text = f"{data['name']}\n\n"

        if data["notes"]:
            text += f"{data['notes']}\n\n"

        if data["created_by"] and data["created_by"]["gid"]:
            creator = self.get_user(data["created_by"]["gid"])["name"]
            created_date = self.format_date(data["created_at"])
            text += f"Created by: {creator} on {created_date}\n"

        if data["due_on"]:
            due_date = self.format_date(data["due_on"])
            text += f"Due date: {due_date}\n"

        if data["completed_at"]:
            completed_date = self.format_date(data["completed_at"])
            text += f"Completed on: {completed_date}\n"

        text += "\n"
        return text

    def _fetch_and_add_comments(self, task_gid: str) -> str:
        text = ""
        stories_opts: Dict[str, str] = {}
        story_start = time.time()
        stories = self.stories_api.get_stories_for_task(task_gid, stories_opts)

        story_count = 0
        comment_count = 0

        for story in stories:
            story_count += 1
            if story["resource_subtype"] == "comment_added":
                comment = self.stories_api.get_story(
                    story["gid"], opts={"opt_fields": "text,created_by,created_at"}
                )
                commenter = self.get_user(comment["created_by"]["gid"])["name"]
                text += f"Comment by {commenter}: {comment['text']}\n\n"
                comment_count += 1

        story_duration = time.time() - story_start
        logger.debug(
            f"Processed {story_count} stories (including {comment_count} comments) in {story_duration:.2f} seconds"
        )

        return text

    def get_user(self, user_gid: str) -> Dict:
        if self._user is not None:
            return self._user
        self._user = self.users_api.get_user(user_gid, {"opt_fields": "name,email"})

        if not self._user:
            logger.warning(f"Unable to fetch user information for user_gid: {user_gid}")
            return {"name": "Unknown"}
        return self._user

    def format_date(self, date_str: str) -> str:
        date = datetime.fromisoformat(date_str)
        return time.strftime("%Y-%m-%d", date.timetuple())

    def get_time(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
