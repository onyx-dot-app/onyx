"""The Drive search query language (the `q` parameter of files.list).

Supports the terms indexers use: comparisons on mimeType, name, trashed,
starred, modifiedTime and createdTime; `'<id>' in parents`; `'<email>' in
owners`, writers and readers; `name contains`; and `and`, `or`, `not` and
parentheses. Anything else raises QueryError, which the API answers with 400.
"""

import re
from datetime import datetime, timezone
from typing import Literal, cast

from pydantic import BaseModel

from .corpus import Corpus, MockFile

Op = Literal["=", "!=", "<", "<=", ">", ">="]


class QueryError(ValueError):
    pass


class CompareNode(BaseModel):
    field: str
    op: Op
    value: str | bool
    # Set for modifiedTime and createdTime.
    time_value: datetime | None = None


class InNode(BaseModel):
    value: str
    field: str


class ContainsNode(BaseModel):
    field: str
    value: str


class NotNode(BaseModel):
    child: "QueryNode"


class AndNode(BaseModel):
    children: list["QueryNode"]


class OrNode(BaseModel):
    children: list["QueryNode"]


QueryNode = CompareNode | InNode | ContainsNode | NotNode | AndNode | OrNode

_TOKEN = re.compile(
    r"\s*(?:(?P<string>'(?:[^'\\]|\\.)*')|(?P<op>!=|<=|>=|=|<|>)|(?P<paren>[()])"
    r"|(?P<word>[A-Za-z_][A-Za-z0-9_.]*))"
)
_TIME_FIELDS = {"modifiedTime", "createdTime"}
_BOOL_FIELDS = {"trashed", "starred", "sharedWithMe"}
_IN_FIELDS = {"parents", "owners", "writers", "readers"}
_ALL_ROLES = {"owner", "organizer", "fileOrganizer", "writer", "commenter", "reader"}


def _tokenize(query: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    position = 0
    stripped = query.rstrip()
    while position < len(stripped):
        match = _TOKEN.match(stripped, position)
        if match is None or match.end() == position:
            raise QueryError(f"Invalid query near {stripped[position:]!r}")
        kind = match.lastgroup or ""
        text = match.group(kind)
        if kind == "string":
            text = re.sub(r"\\(.)", r"\1", text[1:-1])
        tokens.append((kind, text))
        position = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self._tokens = tokens
        self._i = 0

    def parse(self) -> QueryNode:
        node = self._or()
        if self._i != len(self._tokens):
            raise QueryError(f"Unexpected {self._tokens[self._i][1]!r}")
        return node

    def _peek_word(self) -> str | None:
        if self._i < len(self._tokens) and self._tokens[self._i][0] == "word":
            return self._tokens[self._i][1].lower()
        return None

    def _take(self) -> tuple[str, str]:
        if self._i >= len(self._tokens):
            raise QueryError("Unexpected end of query")
        token = self._tokens[self._i]
        self._i += 1
        return token

    def _or(self) -> QueryNode:
        children = [self._and()]
        while self._peek_word() == "or":
            self._i += 1
            children.append(self._and())
        return children[0] if len(children) == 1 else OrNode(children=children)

    def _and(self) -> QueryNode:
        children = [self._not()]
        while self._peek_word() == "and":
            self._i += 1
            children.append(self._not())
        return children[0] if len(children) == 1 else AndNode(children=children)

    def _not(self) -> QueryNode:
        if self._peek_word() == "not":
            self._i += 1
            return NotNode(child=self._not())
        return self._atom()

    def _atom(self) -> QueryNode:
        kind, text = self._take()
        if kind == "paren" and text == "(":
            node = self._or()
            closing = self._take()
            if closing != ("paren", ")"):
                raise QueryError("Missing closing parenthesis")
            return node
        if kind == "string":
            keyword = self._take()
            if keyword[0] != "word" or keyword[1].lower() != "in":
                raise QueryError(f"Expected 'in' after {text!r}")
            field_kind, field = self._take()
            if field_kind != "word" or field not in _IN_FIELDS:
                raise QueryError(f"Unsupported 'in' field {field!r}")
            return InNode(value=text, field=field)
        if kind != "word":
            raise QueryError(f"Unexpected {text!r}")
        field = text
        op_kind, op = self._take()
        if op_kind == "word" and op.lower() == "contains":
            value_kind, value = self._take()
            if value_kind != "string" or field not in ("name", "fullText"):
                raise QueryError(f"Unsupported contains on {field!r}")
            return ContainsNode(field=field, value=value)
        if op_kind != "op":
            raise QueryError(f"Expected an operator after {field!r}")
        value_kind, raw_value = self._take()
        value: str | bool
        if value_kind == "word" and raw_value.lower() in ("true", "false"):
            value = raw_value.lower() == "true"
        elif value_kind == "string":
            value = raw_value
        else:
            raise QueryError(f"Invalid value {raw_value!r}")
        _validate_compare(field, op, value)
        time_value = (
            parse_time(value)
            if field in _TIME_FIELDS and isinstance(value, str)
            else None
        )
        # The tokenizer only yields the operators of Op.
        return CompareNode(
            field=field, op=cast(Op, op), value=value, time_value=time_value
        )


def _validate_compare(field: str, op: str, value: str | bool) -> None:
    if field in _BOOL_FIELDS:
        if not isinstance(value, bool) or op not in ("=", "!="):
            raise QueryError(f"{field} compares only with = or != true/false")
    elif field in _TIME_FIELDS:
        if not isinstance(value, str):
            raise QueryError(f"{field} needs a date")
        parse_time(value)
    elif field in ("mimeType", "name"):
        if not isinstance(value, str) or op not in ("=", "!="):
            raise QueryError(f"{field} compares only with = or !=")
    else:
        raise QueryError(f"Unsupported field {field!r}")


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as e:
        raise QueryError(f"Invalid date {value!r}") from e
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_query(query: str) -> QueryNode | None:
    if not query.strip():
        return None
    return _Parser(_tokenize(query)).parse()


def resolve_parent(value: str, me: str, corpus: Corpus) -> str:
    """The folder id of a parent in a query. ``root`` is the caller's My Drive
    root."""
    if value != "root":
        return value
    root = corpus.root_of(me)
    return root.id if root is not None else value


def required_parent(node: QueryNode | None) -> str | None:
    """A parent every match must have, so a listing can start from its
    children instead of every file."""
    if isinstance(node, InNode) and node.field == "parents":
        return node.value
    if isinstance(node, AndNode):
        for child in node.children:
            parent = required_parent(child)
            if parent is not None:
                return parent
    return None


def _compare(
    left: str | datetime | bool, op: str, right: str | datetime | bool
) -> bool:
    if op == "=":
        return left == right
    if op == "!=":
        return left != right
    if not isinstance(left, datetime) or not isinstance(right, datetime):
        return False
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    return left >= right


def matches(node: QueryNode | None, file: MockFile, me: str, corpus: Corpus) -> bool:
    if node is None:
        return True
    if isinstance(node, AndNode):
        return all(matches(child, file, me, corpus) for child in node.children)
    if isinstance(node, OrNode):
        return any(matches(child, file, me, corpus) for child in node.children)
    if isinstance(node, NotNode):
        return not matches(node.child, file, me, corpus)
    if isinstance(node, ContainsNode):
        return node.value.lower() in file.name.lower()
    if isinstance(node, InNode):
        value = me if node.value == "me" else node.value
        if node.field == "parents":
            return resolve_parent(value, me, corpus) in file.parents
        if node.field == "owners":
            return file.owner == value
        roles = {"owner", "organizer", "fileOrganizer", "writer"}
        if node.field == "readers":
            roles |= {"commenter", "reader"}
        permissions = list(file.permissions)
        if file.drive_id is not None:
            # A shared drive item inherits the roles of the drive's members.
            permissions += corpus.drives[file.drive_id].members
        return any(p.email_address == value and p.role in roles for p in permissions)
    if node.field == "mimeType":
        return _compare(file.mime_type, node.op, node.value)
    if node.field == "name":
        return _compare(file.name, node.op, node.value)
    if node.field == "trashed" or node.field == "starred":
        return _compare(False, node.op, node.value)
    if node.field == "sharedWithMe":
        # A file of a shared drive has no owner, and can be shared directly.
        shared = file.owner != me and corpus.has_direct_role(me, file, _ALL_ROLES)
        return _compare(shared, node.op, node.value)
    if node.time_value is None:
        return False
    actual = file.modified_time if node.field == "modifiedTime" else file.created_time
    return _compare(actual, node.op, node.time_value)
