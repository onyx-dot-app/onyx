"""Jira resource definitions.

This module implements the Resource classes that translate JSON from Jira REST
resources into usable objects.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import ParseResult, urlparse, urlunparse

from requests import Response
from requests.structures import CaseInsensitiveDict

from jira.resilientsession import ResilientSession, parse_errors
from jira.utils import json_loads, remove_empty_attributes, threaded_requests

if TYPE_CHECKING:
    from jira.client import JIRA

    AnyLike = Any
else:

    class AnyLike:
        """Dummy subclass of base object class for when type checker is not running."""

        pass


__all__ = (
    "Resource",
    "Issue",
    "Comment",
    "Project",
    "Attachment",
    "Component",
    "Dashboard",
    "DashboardItemProperty",
    "DashboardItemPropertyKey",
    "Filter",
    "DashboardGadget",
    "Votes",
    "PermissionScheme",
    "Watchers",
    "Worklog",
    "IssueLink",
    "IssueLinkType",
    "IssueProperty",
    "IssueSecurityLevelScheme",
    "IssueType",
    "IssueTypeScheme",
    "NotificationScheme",
    "Priority",
    "PriorityScheme",
    "Version",
    "WorkflowScheme",
    "Role",
    "Resolution",
    "SecurityLevel",
    "Status",
    "User",
    "Group",
    "CustomFieldOption",
    "RemoteLink",
    "Customer",
    "ServiceDesk",
    "RequestType",
    "resource_class_map",
    "PinnedComment",
)

logging.getLogger("jira").addHandler(logging.NullHandler())


class Resource:
    """Models a URL-addressable resource in the Jira REST API.

    All Resource objects provide the following:
    ``find()`` -- get a resource from the server and load it into the current object (though clients should use the methods in the JIRA class instead of this method directly)
    ``update()`` -- changes the value of this resource on the server and returns a new resource object for it
    ``delete()`` -- deletes this resource from the server
    ``self`` -- the URL of this resource on the server
    ``raw`` -- dict of properties parsed out of the JSON response from the server

    Subclasses will implement ``update()`` and ``delete()`` as appropriate for the specific resource.

    All Resources have a resource path of the form:

    * ``issue``
    * ``project/{0}``
    * ``issue/{0}/votes``
    * ``issue/{0}/comment/{1}``

    where the bracketed numerals are placeholders for ID values that are filled in from the ``ids`` parameter to ``find()``.
    """

    JIRA_BASE_URL = "{server}/rest/{rest_path}/{rest_api_version}/{path}"

    # A prioritized list of the keys in self.raw most likely to contain a
    # human readable name or identifier, or that offer other key information.
    _READABLE_IDS = (
        "displayName",
        "key",
        "name",
        "accountId",
        "filename",
        "value",
        "scope",
        "votes",
        "id",
        "mimeType",
        "closed",
    )

    # A list of properties that should uniquely identify a Resource object.
    # Each of these properties should be hashable, usually strings
    _HASH_IDS = (
        "self",
        "type",
        "key",
        "id",
        "name",
    )

    def __init__(
        self,
        resource: str,
        options: dict[str, Any],
        session: ResilientSession,
        base_url: str = JIRA_BASE_URL,
    ):
        """Initializes a generic resource.

        Args:
            resource (str): The name of the resource.
            options (Dict[str,str]): Options for the new resource
            session (ResilientSession): Session used for the resource.
            base_url (Optional[str]): The Base Jira url.

        """
        self._resource = resource
        self._options = options
        self._session = session
        self._base_url = base_url

        # Explicitly define as None, so we know when a resource has actually been loaded
        self.raw: dict[str, Any] | None = None

    def __str__(self) -> str:
        """Return the first value we find that is likely to be human-readable.

        Returns:
            str
        """
        if self.raw:
            for name in self._READABLE_IDS:
                if name in self.raw:
                    pretty_name = str(self.raw[name])
                    # Include any child to support nested select fields.
                    if hasattr(self, "child"):
                        pretty_name += " - " + str(self.child)
                    return pretty_name

        # If all else fails, use repr to make sure we get something.
        return repr(self)

    def __repr__(self) -> str:
        """Identify the class and include any and all relevant values.

        Returns:
            str
        """
        names: list[str] = []
        if self.raw:
            for name in self._READABLE_IDS:
                if name in self.raw:
                    names.append(name + "=" + repr(self.raw[name]))
        if not names:
            return f"<JIRA {self.__class__.__name__} at {id(self)}>"
        return f"<JIRA {self.__class__.__name__}: {', '.join(names)}>"

    def __getattr__(self, item: str) -> Any:
        """Allow access of attributes via names.

        Args:
            item (str): Attribute Name

        Raises:
            AttributeError: When attribute does not exist.

        Returns:
            Any: Attribute value.
        """
        try:
            return self[item]  # type: ignore
        except Exception as e:
            if hasattr(self, "raw") and self.raw is not None and item in self.raw:
                return self.raw[item]
            else:
                raise AttributeError(
                    f"{self.__class__!r} object has no attribute {item!r} ({e})"
                )

    def __getstate__(self) -> dict[str, Any]:
        """Pickling the resource."""
        return vars(self)

    def __setstate__(self, raw_pickled: dict[str, Any]):
        """Unpickling of the resource."""
        # https://stackoverflow.com/a/50888571/7724187
        vars(self).update(raw_pickled)

    def __hash__(self) -> int:
        """Hash calculation.

        We try to find unique identifier like properties to form our hash object.
        Technically 'self', if present, is the unique URL to the object, and should be sufficient to generate a unique hash.
        """
        hash_list = []
        for a in self._HASH_IDS:
            if hasattr(self, a):
                hash_list.append(getattr(self, a))

        if hash_list:
            return hash(tuple(hash_list))
        else:
            raise TypeError(f"'{self.__class__}' is not hashable")

    def __eq__(self, other: Any) -> bool:
        """Default equality test.

        Checks the types look about right and that the relevant attributes that uniquely identify a resource are equal.
        """
        return isinstance(other, self.__class__) and all(
            [
                getattr(self, a) == getattr(other, a)
                for a in self._HASH_IDS
                if hasattr(self, a)
            ]
        )

    def find(
        self,
        id: tuple[str, ...] | int | str,
        params: dict[str, str] | None = None,
    ):
        """Finds a resource based on the input parameters.

        Args:
            id (Union[Tuple[str, str], int, str]): id
            params (Optional[Dict[str, str]]): params
        """
        if params is None:
            params = {}

        if isinstance(id, tuple):
            path = self._resource.format(*id)
        else:
            path = self._resource.format(id)
        url = self._get_url(path)
        self._find_by_url(url, params)

    def _find_by_url(
        self,
        url: str,
        params: dict[str, str] | None = None,
    ):
        """Finds a resource on the specified url.

        The resource is loaded with the JSON data returned by doing a
        request on the specified url.

        Args:
            url (str): url
            params (Optional[Dict[str, str]]): params
        """
        self._load(url, params=params)

    def _get_url(self, path: str) -> str:
        """Gets the url for the specified path.

        Args:
            path (str): str

        Returns:
            str
        """
        options = self._options.copy()
        options.update({"path": path})
        return self._base_url.format(**options)

    def _validate_self_self_url(self) -> None:
        """In the case of a proxy, use the configured option server URL."""
        if getattr(self, "self", None):
            self.self: str
            self_parsed = urlparse(self.self)
            server_parsed = urlparse(self._options["server"])
            if self_parsed.netloc != server_parsed.netloc:
                self.self = urlunparse(
                    ParseResult(
                        scheme=server_parsed.scheme,
                        netloc=server_parsed.netloc,
                        path=self_parsed.path,
                        params=self_parsed.params,
                        query=self_parsed.query,
                        fragment=self_parsed.fragment,
                    )
                )

    def update(
        self,
        fields: dict[str, Any] | None = None,
        async_: bool | None = None,
        jira: JIRA | None = None,
        notify: bool = True,
        **kwargs: Any,
    ):
        """Update this resource on the server.

        Keyword arguments are marshalled into a dict before being sent. If this resource doesn't support ``PUT``, a :py:exc:`.JIRAError`
        will be raised; subclasses that specialize this method will only raise errors in case of user error.

        Args:
            fields (Optional[Dict[str, Any]]): Fields which should be updated for the object.
            async_ (Optional[bool]): True to add the request to the queue, so it can be executed later using async_run()
            jira (jira.client.JIRA): Instance of Jira Client
            notify (bool): True to notify watchers about the update, sets parameter notifyUsers. (Default: ``True``).
              Admin or project admin permissions are required to disable the notification.
            kwargs (Any): extra arguments to the PUT request.
        """
        if async_ is None:
            async_: bool = self._options["async"]  # type: ignore # redefinition

        data = {}
        if fields is not None:
            data.update(fields)
        data.update(kwargs)

        if not notify:
            querystring = "?notifyUsers=false"
        else:
            querystring = ""

        self._validate_self_self_url()
        r = self._session.put(self.self + querystring, data=json.dumps(data))
        if "autofix" in self._options and r.status_code == 400:
            user = None
            error_list = parse_errors(r)
            logging.error(error_list)
            if (
                "The reporter specified is not a user." in error_list
                and "reporter" not in data["fields"]
            ):
                logging.warning(
                    "autofix: setting reporter to '{}' and retrying the update.".format(
                        self._options["autofix"]
                    )
                )
                data["fields"]["reporter"] = {"name": self._options["autofix"]}

            if (
                "Issues must be assigned." in error_list
                and "assignee" not in data["fields"]
            ):
                logging.warning(
                    "autofix: setting assignee to '{}' for {} and retrying the update.".format(
                        self._options["autofix"], self.key
                    )
                )
                data["fields"]["assignee"] = {"name": self._options["autofix"]}

            if (
                "Issue type is a sub-task but parent issue key or id not specified."
                in error_list
            ):
                logging.warning(
                    "autofix: trying to fix sub-task without parent by converting to it to bug"
                )
                data["fields"]["issuetype"] = {"name": "Bug"}
            if (
                "The summary is invalid because it contains newline characters."
                in error_list
            ):
                logging.warning("autofix: trying to fix newline in summary")
                data["fields"]["summary"] = self.fields.summary.replace("/n", "")
            for error in error_list:
                if re.search(
                    r"^User '(.*)' was not found in the system\.", error, re.U
                ):
                    m = re.search(
                        r"^User '(.*)' was not found in the system\.", error, re.U
                    )
                    if m:
                        user = m.groups()[0]
                    else:
                        raise NotImplementedError()
                if re.search(r"^User '(.*)' does not exist\.", error):
                    m = re.search(r"^User '(.*)' does not exist\.", error)
                    if m:
                        user = m.groups()[0]
                    else:
                        raise NotImplementedError()

            if user and jira:
                logging.warning(
                    f"Trying to add missing orphan user '{user}' in order to complete the previous failed operation."
                )
                jira.add_user(user, "noreply@example.com", 10100, active=False)
                # if 'assignee' not in data['fields']:
                #    logging.warning("autofix: setting assignee to '%s' and retrying the update." % self._options['autofix'])
                #    data['fields']['assignee'] = {'name': self._options['autofix']}
            # EXPERIMENTAL --->
            if async_:  # FIXME: no async
                if not hasattr(self._session, "_async_jobs"):
                    self._session._async_jobs = set()  # type: ignore
                self._session._async_jobs.add(  # type: ignore
                    threaded_requests.put(  # type: ignore
                        self.self, data=json.dumps(data)
                    )
                )
            else:
                r = self._session.put(self.self, data=json.dumps(data))

        time.sleep(self._options["delay_reload"])
        self._load(self.self)

    def delete(self, params: dict[str, Any] | None = None) -> Response | None:
        """Delete this resource from the server, passing the specified query parameters.

        If this resource doesn't support ``DELETE``, a :py:exc:`.JIRAError` will be raised; subclasses that specialize this method will
        only raise errors in case of user error.

        Args:
            params: Parameters for the delete request.

        Returns:
            Optional[Response]: Returns None if async
        """
        self._validate_self_self_url()
        if self._options["async"]:
            # FIXME: mypy doesn't think this should work
            if not hasattr(self._session, "_async_jobs"):
                self._session._async_jobs = set()  # type: ignore
            self._session._async_jobs.add(  # type: ignore
                threaded_requests.delete(url=self.self, params=params)  # type: ignore
            )
            return None
        else:
            return self._session.delete(url=self.self, params=params)

    def _load(
        self,
        url: str,
        headers=CaseInsensitiveDict(),
        params: dict[str, str] | None = None,
        path: str | None = None,
    ):
        """Load a resource.

        Args:
            url (str): url
            headers (Optional[CaseInsensitiveDict]): headers. Defaults to CaseInsensitiveDict().
            params (Optional[Dict[str,str]]): params to get request. Defaults to None.
            path (Optional[str]): field to get. Defaults to None.

        Raises:
            ValueError: If json cannot be loaded
        """
        r = self._session.get(url, headers=headers, params=params)
        try:
            j = json_loads(r)
        except ValueError as e:
            logging.error(f"{e}:\n{r.text}")
            raise e
        if path:
            j = j[path]
        self._parse_raw(j)

    def _parse_raw(self, raw: dict[str, Any]):
        """Parse a raw dictionary to create a resource.

        Args:
            raw (Dict[str, Any])
        """
        self.raw = raw
        if not raw:
            raise NotImplementedError(f"We cannot instantiate empty resources: {raw}")
        dict2resource(raw, self, self._options, self._session)

    def _default_headers(self, user_headers):
        # result = dict(user_headers)
        # result['accept'] = 'application/json'
        return CaseInsensitiveDict(
            self._options["headers"].items() + user_headers.items()
        )


class Attachment(Resource):
    """An issue attachment."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "attachment/{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)

    def get(self):
        """Return the file content as a string."""
        r = self._session.get(self.content, headers={"Accept": "*/*"})
        return r.content

    def iter_content(self, chunk_size=1024):
        """Return the file content as an iterable stream."""
        r = self._session.get(self.content, stream=True)
        return r.iter_content(chunk_size)


class Component(Resource):
    """A project component."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "component/{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)

    def delete(self, moveIssuesTo: str | None = None):  # type: ignore[override]
        """Delete this component from the server.

        Args:
            moveIssuesTo: the name of the component to which to move any issues this component is applied
        """
        params = {}
        if moveIssuesTo is not None:
            params["moveIssuesTo"] = moveIssuesTo

        super().delete(params)


class CustomFieldOption(Resource):
    """An existing option for a custom issue field."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "customFieldOption/{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class Dashboard(Resource):
    """A Jira dashboard."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "dashboard/{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.gadgets: list[DashboardGadget] = []
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class DashboardItemPropertyKey(Resource):
    """A jira dashboard item property key."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "dashboard/{0}/items/{1}/properties", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class DashboardItemProperty(Resource):
    """A jira dashboard item."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(
            self, "dashboard/{0}/items/{1}/properties/{2}", options, session
        )
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)

    def update(  # type: ignore[override] # incompatible supertype ignored
        self, dashboard_id: str, item_id: str, value: dict[str, Any]
    ) -> DashboardItemProperty:
        """Update this resource on the server.

        Keyword arguments are marshalled into a dict before being sent. If this resource doesn't support ``PUT``, a :py:exc:`.JIRAError`
        will be raised; subclasses that specialize this method will only raise errors in case of user error.

        Args:
          dashboard_id (str): The ``id`` if the dashboard.
          item_id (str): The id of the dashboard item (``DashboardGadget``) to target.
          value (dict[str, Any]): The value of the targeted property key.

        Returns:
          DashboardItemProperty
        """
        options = self._options.copy()
        options["path"] = (
            f"dashboard/{dashboard_id}/items/{item_id}/properties/{self.key}"
        )
        self.raw["value"].update(value)
        self._session.put(self.JIRA_BASE_URL.format(**options), self.raw["value"])

        return DashboardItemProperty(self._options, self._session, raw=self.raw)

    def delete(self, dashboard_id: str, item_id: str) -> Response:  # type: ignore[override] # incompatible supertype ignored
        """Delete dashboard item property.

        Args:
          dashboard_id (str): The ``id`` of the dashboard.
          item_id (str): The ``id`` of the dashboard item (``DashboardGadget``).


        Returns:
          Response
        """
        options = self._options.copy()
        options["path"] = (
            f"dashboard/{dashboard_id}/items/{item_id}/properties/{self.key}"
        )

        return self._session.delete(self.JIRA_BASE_URL.format(**options))


class DashboardGadget(Resource):
    """A jira dashboard gadget."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "dashboard/{0}/gadget/{1}", options, session)
        if raw:
            self._parse_raw(raw)
        self.item_properties: list[DashboardItemProperty] = []
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)

    def update(  # type: ignore[override] # incompatible supertype ignored
        self,
        dashboard_id: str,
        color: str | None = None,
        position: dict[str, Any] | None = None,
        title: str | None = None,
    ) -> DashboardGadget:
        """Update this resource on the server.

        Keyword arguments are marshalled into a dict before being sent. If this resource doesn't support ``PUT``, a :py:exc:`.JIRAError`
        will be raised; subclasses that specialize this method will only raise errors in case of user error.

        Args:
          dashboard_id (str): The ``id`` of the dashboard to add the gadget to `required`.
          color (str): The color of the gadget, should be one of: blue, red, yellow,
              green, cyan, purple, gray, or white.
          ignore_uri_and_module_key_validation (bool): Whether to ignore the
              validation of the module key and URI. For example, when a gadget is created
              that is part of an application that is not installed.
          position (dict[str, int]): A dictionary containing position information like -
              `{"column": 0, "row", 1}`.
          title (str): The title of the gadget.

        Returns:
          ``DashboardGadget``
        """
        data = remove_empty_attributes(
            {"color": color, "position": position, "title": title}
        )
        options = self._options.copy()
        options["path"] = f"dashboard/{dashboard_id}/gadget/{self.id}"

        self._session.put(self.JIRA_BASE_URL.format(**options), json=data)
        options["path"] = f"dashboard/{dashboard_id}/gadget"

        return next(
            DashboardGadget(self._options, self._session, raw=gadget)
            for gadget in self._session.get(
                self.JIRA_BASE_URL.format(**options)
            ).json()["gadgets"]
            if gadget["id"] == self.id
        )

    def delete(self, dashboard_id: str) -> Response:  # type: ignore[override] # incompatible supertype ignored
        """Delete gadget from dashboard.

        Args:
          dashboard_id (str): The ``id`` of the dashboard.

        Returns:
          Response
        """
        options = self._options.copy()
        options["path"] = f"dashboard/{dashboard_id}/gadget/{self.id}"

        return self._session.delete(self.JIRA_BASE_URL.format(**options))


class Field(Resource):
    """An issue field.

    A field cannot be fetched from the Jira API individually, but paginated lists of fields are returned by some endpoints.
    """

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "field/{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class Filter(Resource):
    """An issue navigator filter."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "filter/{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class Issue(Resource):
    """A Jira issue."""

    class _IssueFields(AnyLike):
        class _Comment:
            def __init__(self) -> None:
                self.comments: list[Comment] = []

        class _Worklog:
            def __init__(self) -> None:
                self.worklogs: list[Worklog] = []

        def __init__(self):
            self.assignee: UnknownResource | None = None
            self.attachment: list[Attachment] = []
            self.comment = self._Comment()
            self.created: str
            self.description: str | None = None
            self.duedate: str | None = None
            self.issuelinks: list[IssueLink] = []
            self.issuetype: IssueType
            self.labels: list[str] = []
            self.priority: Priority
            self.project: Project
            self.reporter: UnknownResource
            self.resolution: Resolution | None = None
            self.security: SecurityLevel | None = None
            self.status: Status
            self.statuscategorychangedate: str | None = None
            self.summary: str
            self.timetracking: TimeTracking
            self.versions: list[Version] = []
            self.votes: Votes
            self.watchers: Watchers
            self.worklog = self._Worklog()

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "issue/{0}", options, session)

        self.fields: Issue._IssueFields
        self.id: str
        self.key: str
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)

    def update(  # type: ignore[override] # incompatible supertype ignored
        self,
        fields: dict[str, Any] | None = None,
        update: dict[str, Any] | None = None,
        async_: bool | None = None,
        jira: JIRA | None = None,
        notify: bool = True,
        **fieldargs,
    ):
        """Update this issue on the server.

        Each keyword argument (other than the predefined ones) is treated as a field name and the argument's value is treated as
        the intended value for that field -- if the fields argument is used, all other keyword arguments will be ignored.

        Jira projects may contain many issue types. Some issue screens have different requirements for fields in an issue.
        This information is available through the :py:meth:`.JIRA.editmeta` method.
        Further examples are available here: https://developer.atlassian.com/display/JIRADEV/JIRA+REST+API+Example+-+Edit+issues

        Args:
            fields (Dict[str,Any]): a dict containing field names and the values to use
            update (Dict[str,Any]): a dict containing update the operations to apply
            async_ (Optional[bool]): True to add the request to the queue, so it can be executed later using async_run() (Default: ``None``))
            jira (Optional[jira.client.JIRA]): JIRA instance.
            notify (bool): True to notify watchers about the update, sets parameter notifyUsers. (Default: ``True``).
              Admin or project admin permissions are required to disable the notification.
            fieldargs (dict): keyword arguments will generally be merged into fields, except lists, which will be merged into updates
        """
        data = {}
        if fields is not None:
            fields_dict = fields
        else:
            fields_dict = {}
        data["fields"] = fields_dict
        if update is not None:
            update_dict = update
        else:
            update_dict = {}
        data["update"] = update_dict
        for field in sorted(fieldargs.keys()):
            value = fieldargs[field]
            # apply some heuristics to make certain changes easier
            if isinstance(value, str):
                if field == "assignee" or field == "reporter":
                    fields_dict[field] = {"name": value}
                elif field == "comment":
                    if "comment" not in update_dict:
                        update_dict["comment"] = []
                    update_dict["comment"].append({"add": {"body": value}})
                else:
                    fields_dict[field] = value
            elif isinstance(value, list):
                if field not in update_dict:
                    update_dict[field] = []
                update_dict[field].extend(value)
            else:
                fields_dict[field] = value

        super().update(async_=async_, jira=jira, notify=notify, fields=data)

    def get_field(self, field_name: str) -> Any:
        """Obtain the (parsed) value from the Issue's field.

        Args:
            field_name (str): The name of the field to get

        Raises:
            AttributeError: If the field does not exist or if the field starts with an ``_``

        Returns:
            Any: Returns the parsed data stored in the field. For example, "project" would be of class :py:class:`Project`
        """
        if field_name.startswith("_"):
            raise AttributeError(
                f"An issue field_name cannot start with underscore (_): {field_name}",
                field_name,
            )
        else:
            return getattr(self.fields, field_name)

    def add_field_value(self, field: str, value: str):
        """Add a value to a field that supports multiple values, without resetting the existing values.

        This should work with: labels, multiple checkbox lists, multiple select

        Args:
            field (str): The field name
            value (str): The field's value
        """
        super().update(fields={"update": {field: [{"add": value}]}})

    def delete(self, deleteSubtasks=False):
        """Delete this issue from the server.

        Args:
            deleteSubtasks (bool): True to also delete subtasks. If any are present the Issue won't be deleted (Default: ``False``)
        """
        super().delete(params={"deleteSubtasks": deleteSubtasks})

    def permalink(self):
        """Get the URL of the issue, the browsable one not the REST one.

        Returns:
            str: URL of the issue
        """
        return f"{self._options['server']}/browse/{self.key}"


class Comment(Resource):
    """An issue comment."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "issue/{0}/comment/{1}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)

    def update(  # type: ignore[override]
        # The above ignore is added because we've added new parameters and order of
        # parameters is different.
        # Will need to be solved in a major version bump.
        self,
        fields: dict[str, Any] | None = None,
        async_: bool | None = None,
        jira: JIRA | None = None,
        body: str = "",
        visibility: dict[str, str] | None = None,
        is_internal: bool = False,
        notify: bool = True,
    ):
        """Update a comment.

        Keyword arguments are marshalled into a dict before being sent.

        Args:
            fields (Optional[Dict[str, Any]]): DEPRECATED => a comment doesn't have fields
            async_ (Optional[bool]): True to add the request to the queue, so it can be executed later using async_run() (Default: ``None``))
            jira (jira.client.JIRA): Instance of Jira Client
            visibility (Optional[Dict[str, str]]): a dict containing two entries: "type" and "value".
              "type" is 'role' (or 'group' if the Jira server has configured comment visibility for groups)
              "value" is the name of the role (or group) to which viewing of this comment will be restricted.
            body (str): New text of the comment
            is_internal (bool): True to mark the comment as 'Internal' in Jira Service Desk (Default: ``False``)
            notify (bool): True to notify watchers about the update, sets parameter notifyUsers. (Default: ``True``).
              Admin or project admin permissions are required to disable the notification.
        """
        data: dict[str, Any] = {}
        if body:
            data["body"] = body
        if visibility:
            data["visibility"] = visibility
        if is_internal:
            data["properties"] = [
                {"key": "sd.public.comment", "value": {"internal": is_internal}}
            ]

        super().update(async_=async_, jira=jira, notify=notify, fields=data)


class PinnedComment(Resource):
    """Pinned comment on an issue."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "issue/{0}/pinned-comments", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class RemoteLink(Resource):
    """A link to a remote application from an issue."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "issue/{0}/remotelink/{1}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)

    def update(  # type: ignore[override]
        self,
        object: dict[str, Any] | None,
        globalId=None,
        application=None,
        relationship=None,
    ):
        """Update a RemoteLink. 'object' is required.

        For definitions of the allowable fields for 'object' and the keyword arguments 'globalId', 'application' and 'relationship',
        see https://developer.atlassian.com/display/JIRADEV/JIRA+REST+API+for+Remote+Issue+Links.

        Args:
            object: the link details to add (see the above link for details)
            globalId: unique ID for the link (see the above link for details)
            application: application information for the link (see the above link for details)
            relationship: relationship description for the link (see the above link for details)
        """
        data = {"object": object}
        if globalId is not None:
            data["globalId"] = globalId
        if application is not None:
            data["application"] = application
        if relationship is not None:
            data["relationship"] = relationship

        # https://github.com/pycontribs/jira/issues/1881
        super().update(**data)  # type: ignore[arg-type]


class Votes(Resource):
    """Vote information on an issue."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "issue/{0}/votes", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class IssueTypeScheme(Resource):
    """An issue type scheme."""

    def __init__(self, options, session, raw=None):
        Resource.__init__(self, "issuetypescheme", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class IssueSecurityLevelScheme(Resource):
    """IssueSecurityLevelScheme information on a project."""

    def __init__(self, options, session, raw=None):
        Resource.__init__(
            self, "project/{0}/issuesecuritylevelscheme?expand=user", options, session
        )
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class NotificationScheme(Resource):
    """NotificationScheme information on a project."""

    def __init__(self, options, session, raw=None):
        Resource.__init__(
            self, "project/{0}/notificationscheme?expand=user", options, session
        )
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class PermissionScheme(Resource):
    """Permissionscheme information on a project."""

    def __init__(self, options, session, raw=None):
        Resource.__init__(
            self, "project/{0}/permissionscheme?expand=user", options, session
        )
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class PriorityScheme(Resource):
    """PriorityScheme information on a project."""

    def __init__(self, options, session, raw=None):
        Resource.__init__(
            self, "project/{0}/priorityscheme?expand=user", options, session
        )
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class WorkflowScheme(Resource):
    """WorkflowScheme information on a project."""

    def __init__(self, options, session, raw=None):
        Resource.__init__(
            self, "project/{0}/workflowscheme?expand=user", options, session
        )
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class Watchers(Resource):
    """Watcher information on an issue."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "issue/{0}/watchers", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)

    def delete(self, username):  # type: ignore[override]
        """Remove the specified user from the watchers list."""
        super().delete(params={"username": username})


class TimeTracking(Resource):
    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "issue/{0}/worklog/{1}", options, session)
        self.remainingEstimate = None
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class Worklog(Resource):
    """Worklog on an issue."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "issue/{0}/worklog/{1}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)

    def delete(  # type: ignore[override]
        self, adjustEstimate: str | None = None, newEstimate=None, increaseBy=None
    ):
        """Delete this worklog entry from its associated issue.

        Args:
            adjustEstimate: one of ``new``, ``leave``, ``manual`` or ``auto``.
              ``auto`` is the default and adjusts the estimate automatically.
              ``leave`` leaves the estimate unchanged by this deletion.
            newEstimate: combined with ``adjustEstimate=new``, set the estimate to this value
            increaseBy: combined with ``adjustEstimate=manual``, increase the remaining estimate by this amount
        """
        params = {}
        if adjustEstimate is not None:
            params["adjustEstimate"] = adjustEstimate
        if newEstimate is not None:
            params["newEstimate"] = newEstimate
        if increaseBy is not None:
            params["increaseBy"] = increaseBy

        super().delete(params)


class IssueProperty(Resource):
    """Custom data against an issue."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "issue/{0}/properties/{1}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)

    def _find_by_url(
        self,
        url: str,
        params: dict[str, str] | None = None,
    ):
        super()._find_by_url(url, params)
        # An IssueProperty never returns "self" identifier, set it
        self.self = url


class IssueLink(Resource):
    """Link between two issues."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "issueLink/{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class IssueLinkType(Resource):
    """Type of link between two issues."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "issueLinkType/{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class IssueType(Resource):
    """Type of issue."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "issuetype/{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class Priority(Resource):
    """Priority that can be set on an issue."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "priority/{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class Project(Resource):
    """A Jira project."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "project/{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class Role(Resource):
    """A role inside a project."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "project/{0}/role/{1}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)

    def update(  # type: ignore[override]
        self,
        users: str | list | tuple | None = None,
        groups: str | list | tuple | None = None,
    ):
        """Add the specified users or groups to this project role. One of ``users`` or ``groups`` must be specified.

        Args:
            users (Optional[Union[str,List,Tuple]]): a user or users to add to the role
            groups (Optional[Union[str,List,Tuple]]): a group or groups to add to the role
        """
        if users is not None and isinstance(users, str):
            users = (users,)
        if groups is not None and isinstance(groups, str):
            groups = (groups,)

        data = {
            "id": self.id,
            "categorisedActors": {
                "atlassian-user-role-actor": users,
                "atlassian-group-role-actor": groups,
            },
        }

        super().update(**data)

    def add_user(
        self,
        users: str | list | tuple | None = None,
        groups: str | list | tuple | None = None,
    ):
        """Add the specified users or groups to this project role. One of ``users`` or ``groups`` must be specified.

        Args:
            users (Optional[Union[str,List,Tuple]]): a user or users to add to the role
            groups (Optional[Union[str,List,Tuple]]): a group or groups to add to the role
        """
        if users is not None and isinstance(users, str):
            users = (users,)
        if groups is not None and isinstance(groups, str):
            groups = (groups,)

        data = {"user": users, "group": groups}
        self._session.post(self.self, data=json.dumps(data))


class Resolution(Resource):
    """A resolution for an issue."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "resolution/{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class SecurityLevel(Resource):
    """A security level for an issue or project."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "securitylevel/{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class Status(Resource):
    """Status for an issue."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "status/{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class StatusCategory(Resource):
    """StatusCategory for an issue."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "statuscategory/{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class User(Resource):
    """A Jira user."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
        *,
        _query_param: str = "username",
    ):
        # Handle self-hosted Jira and Jira Cloud differently
        if raw and "accountId" in raw["self"]:
            _query_param = "accountId"

        Resource.__init__(self, f"user?{_query_param}" + "={0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class Group(Resource):
    """A Jira user group."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "group?groupname={0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class Version(Resource):
    """A version of a project."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "version/{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)

    def delete(self, moveFixIssuesTo=None, moveAffectedIssuesTo=None):
        """Delete this project version from the server.

        If neither of the arguments are specified, the version is removed from all issues it is attached to.

        Args:
            moveFixIssuesTo: in issues for which this version is a fix version, add this version to the fix version list
            moveAffectedIssuesTo: in issues for which this version is an affected version, add this version to the affected version list
        """
        params = {}
        if moveFixIssuesTo is not None:
            params["moveFixIssuesTo"] = moveFixIssuesTo
        if moveAffectedIssuesTo is not None:
            params["moveAffectedIssuesTo"] = moveAffectedIssuesTo

        return super().delete(params)

    # TODO: https://github.com/pycontribs/jira/issues/1881
    def update(self, **kwargs):  # type: ignore[override]
        """Update this project version from the server. It is prior used to archive versions.

        Refer to Atlassian REST API `documentation`_.

        .. _documentation: https://developer.atlassian.com/cloud/jira/platform/rest/v2/api-group-project-versions/#api-rest-api-2-version-id-put

        :Example:

            .. code-block:: python

                >> version_id = "10543"
                >> version = JIRA("https://atlassian.org").version(version_id)
                >> print(version.name)
                "some_version_name"
                >> version.update(name="another_name")
                >> print(version.name)
                "another_name"
                >> version.update(archived=True)
                >> print(version.archived)
                True
        """
        data = {}
        for field in kwargs:
            data[field] = kwargs[field]

        super().update(**data)


# Agile


class AgileResource(Resource):
    """A generic Agile resource. Also known as Jira Agile Server, Jira Software and formerly GreenHopper."""

    AGILE_BASE_URL = "{server}/rest/{agile_rest_path}/{agile_rest_api_version}/{path}"

    AGILE_BASE_REST_PATH = "agile"
    """Public API introduced in Jira Agile 6.7.7."""

    def __init__(
        self,
        path: str,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        self.self = ""

        Resource.__init__(self, path, options, session, self.AGILE_BASE_URL)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class Sprint(AgileResource):
    """An Agile sprint."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        AgileResource.__init__(self, "sprint/{0}", options, session, raw)


class Board(AgileResource):
    """An Agile board."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        AgileResource.__init__(self, "board/{id}", options, session, raw)


# Service Desk


class Customer(Resource):
    """A Service Desk customer."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(
            self, "customer", options, session, "{server}/rest/servicedeskapi/{path}"
        )
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class ServiceDesk(Resource):
    """A Service Desk."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(
            self,
            "servicedesk/{0}",
            options,
            session,
            "{server}/rest/servicedeskapi/{path}",
        )
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


class RequestType(Resource):
    """A Service Desk Request Type."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(
            self,
            "servicedesk/{0}/requesttype",
            options,
            session,
            "{server}/rest/servicedeskapi/{path}",
        )

        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


# Utilities


def dict2resource(
    raw: dict[str, Any], top=None, options=None, session=None
) -> PropertyHolder | type[Resource]:
    """Convert a dictionary into a Jira Resource object.

    Recursively walks a dict structure, transforming the properties into attributes on a new ``Resource`` object of the appropriate type
    (if a ``self`` link is present) or a ``PropertyHolder`` object (if no ``self`` link is present).
    """
    if top is None:
        top = PropertyHolder()

    seqs = tuple, list, set, frozenset
    for i, j in raw.items():
        if isinstance(j, dict):
            if "self" in j:
                # to try and help mypy know that cls_for_resource can never be 'Resource'
                resource_class = cast(type[Resource], cls_for_resource(j["self"]))
                resource = cast(
                    type[Resource],
                    resource_class(  # type: ignore
                        options=options,
                        session=session,
                        raw=j,  # type: ignore
                    ),
                )
                setattr(top, i, resource)
            elif i == "timetracking":
                setattr(top, "timetracking", TimeTracking(options, session, j))
            else:
                setattr(top, i, dict2resource(j, options=options, session=session))
        elif isinstance(j, seqs):
            j = cast(list[dict[str, Any]], j)  # help mypy
            seq_list: list[Any] = []
            for seq_elem in j:
                if isinstance(seq_elem, dict):
                    if "self" in seq_elem:
                        # to try and help mypy know that cls_for_resource can never be 'Resource'
                        resource_class = cast(
                            type[Resource], cls_for_resource(seq_elem["self"])
                        )
                        resource = cast(
                            type[Resource],
                            resource_class(  # type: ignore
                                options=options,
                                session=session,
                                raw=seq_elem,  # type: ignore
                            ),
                        )
                        seq_list.append(resource)
                    else:
                        seq_list.append(
                            dict2resource(seq_elem, options=options, session=session)
                        )
                else:
                    seq_list.append(seq_elem)
            setattr(top, i, seq_list)
        else:
            setattr(top, i, j)
    return top


resource_class_map: dict[str, type[Resource]] = {
    # Jira-specific resources
    r"attachment/[^/]+$": Attachment,
    r"component/[^/]+$": Component,
    r"customFieldOption/[^/]+$": CustomFieldOption,
    r"dashboard/[^/]+$": Dashboard,
    r"dashboard/[^/]+/items/[^/]+/properties+$": DashboardItemPropertyKey,
    r"dashboard/[^/]+/items/[^/]+/properties/[^/]+$": DashboardItemProperty,
    r"dashboard/[^/]+/gadget/[^/]+$": DashboardGadget,
    r"filter/[^/]$": Filter,
    r"issue/[^/]+$": Issue,
    r"issue/[^/]+/comment/[^/]+$": Comment,
    r"issue/[^/]+/pinned-comments$": PinnedComment,
    r"issue/[^/]+/votes$": Votes,
    r"issue/[^/]+/watchers$": Watchers,
    r"issue/[^/]+/worklog/[^/]+$": Worklog,
    r"issue/[^/]+/properties/[^/]+$": IssueProperty,
    r"issueLink/[^/]+$": IssueLink,
    r"issueLinkType/[^/]+$": IssueLinkType,
    r"issuetype/[^/]+$": IssueType,
    r"issuetypescheme/[^/]+$": IssueTypeScheme,
    r"project/[^/]+/issuesecuritylevelscheme[^/]+$": IssueSecurityLevelScheme,
    r"project/[^/]+/notificationscheme[^/]+$": NotificationScheme,
    r"project/[^/]+/priorityscheme[^/]+$": PriorityScheme,
    r"priority/[^/]+$": Priority,
    r"project/[^/]+$": Project,
    r"project/[^/]+/role/[^/]+$": Role,
    r"project/[^/]+/permissionscheme[^/]+$": PermissionScheme,
    r"project/[^/]+/workflowscheme[^/]+$": WorkflowScheme,
    r"resolution/[^/]+$": Resolution,
    r"securitylevel/[^/]+$": SecurityLevel,
    r"status/[^/]+$": Status,
    r"statuscategory/[^/]+$": StatusCategory,
    r"user\?(username|key|accountId).+$": User,
    r"group\?groupname.+$": Group,
    r"version/[^/]+$": Version,
    # Agile specific resources
    r"sprints/[^/]+$": Sprint,
    r"views/[^/]+$": Board,
}


class UnknownResource(Resource):
    """A Resource from Jira that is not (yet) supported."""

    def __init__(
        self,
        options: dict[str, str],
        session: ResilientSession,
        raw: dict[str, Any] | None = None,
    ):
        Resource.__init__(self, "unknown{0}", options, session)
        if raw:
            self._parse_raw(raw)
        self.raw: dict[str, Any] = cast(dict[str, Any], self.raw)


def cls_for_resource(resource_literal: str) -> type[Resource]:
    for resource in resource_class_map:
        if re.search(resource, resource_literal):
            return resource_class_map[resource]
    else:
        # Generic Resource cannot directly be used b/c of different constructor signature
        return UnknownResource


class PropertyHolder:
    """An object for storing named attributes."""
