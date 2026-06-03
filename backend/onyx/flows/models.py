"""The flow spec: the declarative document an automation executes.

A spec is stored as JSONB on ``flow.draft_spec`` and ``flow_version.spec``, and
it is the only contract between the editor and the engine. Everything a run
needs lives in here; the engine never reads configuration back out of the ORM
once a run has started.

Two conventions are worth knowing before reading the node types:

* **Adjacency lives on the node.** A node names its successors in ``next``, or
  in a pair of branch lists when it chooses between two paths — ``on_true`` /
  ``on_false`` for a condition, ``on_approve`` / ``on_reject`` for an
  approval. The canvas draws edges from that; keeping one representation
  avoids the spec and the picture disagreeing.
* **Fan-out is explicit.** A node with ``for_each`` set runs once per element
  of that list and records the per-item outputs as its own output. The editor
  fills ``for_each`` in automatically when it notices an upstream list, so the
  convenience lives in the UI while the engine stays predictable — which is
  what you want at 3am reading a run that went wrong.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from onyx.db.enums import FlowNodeKind

# A node id is referenced from other nodes and from run history, so it is held
# to the same shape as a Python identifier in snake_case.
NODE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# Guardrails. These are not tuning knobs — they bound how much damage a
# malformed or hostile spec can do to a worker before validation rejects it.
MAX_NODES_PER_FLOW = 60
MAX_FAN_OUT_ITEMS = 200
MAX_NODE_ATTEMPTS = 4
MAX_HTTP_TIMEOUT_SECONDS = 120.0
MAX_AI_OUTPUT_FIELDS = 20
MAX_CODE_LENGTH = 20_000
MAX_CODE_TIMEOUT_SECONDS = 120.0
MAX_QUESTION_LENGTH = 2000
MAX_RETRY_CHECKS = 60
MAX_RETRY_INTERVAL_SECONDS = 60.0

# A retry node sleeps between checks, and it does that inside one node rather
# than across the graph. Capping the whole window keeps a single step from
# eating the run's 15-minute budget on its own.
MAX_RETRY_WINDOW_SECONDS = 600.0

# A delay longer than this parks the run instead of sleeping. Under it the
# park would cost more than the wait: a resumed run waits for the next sweep
# tick, and a five-second delay should not take half a minute.
INLINE_DELAY_SECONDS = 60.0
MAX_DELAY_SECONDS = 30 * 24 * 60 * 60.0
MAX_MERGE_SOURCES = 10

# What a person can answer at a human step. Stored on the node's run row and
# read back by the engine when the run resumes, so the strings are part of the
# contract rather than display text.
DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"
FlowDecision = Literal["approve", "reject"]


class SpecError(ValueError):
    """A spec that cannot be executed. Surfaced to the editor as 400."""


# ---------------------------------------------------------------------------
# Shared node settings
# ---------------------------------------------------------------------------


class RetryPolicy(BaseModel):
    """How often to re-run a node that raised before giving up.

    Retries re-use the node's row in ``flow_node_run`` and bump ``attempt``,
    so a retried node never duplicates its own history.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(default=1, ge=1, le=MAX_NODE_ATTEMPTS)
    # Seconds to wait before the second attempt. Doubles each attempt after.
    backoff_seconds: float = Field(default=1.0, ge=0.0, le=30.0)


class NodeBase(BaseModel):
    """Fields every node kind carries.

    ``on_error`` is deliberately only stop-or-skip. Routing failures down a
    dedicated branch sounds useful until you have to explain which branch a
    half-finished fan-out took, so it stays out until there is a real need.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = ""
    next: list[str] = Field(default_factory=list)

    # Expression yielding a list. When set, the node runs once per element
    # with `{{ item }}` and `{{ index }}` bound.
    for_each: str | None = None

    on_error: Literal["stop", "skip"] = "stop"
    retry: RetryPolicy = Field(default_factory=RetryPolicy)

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if not NODE_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "must start with a letter and use only lowercase letters, "
                "digits and underscores (max 64 chars)"
            )
        return value

    @model_validator(mode="after")
    def _default_name_to_id(self) -> NodeBase:
        if not self.name:
            object.__setattr__(self, "name", self.id)
        return self

    def successors(self) -> list[str]:
        """Every node id this node can hand control to."""
        return list(self.next)


# ---------------------------------------------------------------------------
# Node kinds
# ---------------------------------------------------------------------------


class HttpNode(NodeBase):
    """Call an HTTP endpoint.

    The workhorse. Between this and the AI node almost any service can be
    driven without waiting for a first-party provider to exist.
    """

    kind: Literal[FlowNodeKind.HTTP] = FlowNodeKind.HTTP

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, str] = Field(default_factory=dict)
    # Rendered through the expression layer, so a body can be assembled from
    # upstream output without a transform node in front of it.
    body: Any = None

    timeout_seconds: float = Field(default=30.0, gt=0.0, le=MAX_HTTP_TIMEOUT_SECONDS)
    # Dot path into the parsed response body. None keeps the whole body.
    result_path: str | None = None
    # 4xx/5xx raises by default. Turn this off to branch on `status` instead.
    fail_on_error_status: bool = True

    @field_validator("url")
    @classmethod
    def _non_empty_url(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class TransformNode(NodeBase):
    """Build a new object out of expressions.

    This is what keeps a `Set` node off the canvas for simple reshaping: each
    key maps to one expression, evaluated against the current context.
    """

    kind: Literal[FlowNodeKind.TRANSFORM] = FlowNodeKind.TRANSFORM

    fields: dict[str, str] = Field(min_length=1)


ConditionOperator = Literal[
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "contains",
    "not_contains",
    "is_empty",
    "is_not_empty",
]

# Operators that compare against nothing, so `right` is meaningless for them.
UNARY_OPERATORS: frozenset[str] = frozenset({"is_empty", "is_not_empty"})


class ConditionNode(NodeBase):
    """Branch on a comparison.

    ``next`` is unused; a condition hands control to ``on_true`` or
    ``on_false``. Either may be empty, which ends that branch.
    """

    kind: Literal[FlowNodeKind.CONDITION] = FlowNodeKind.CONDITION

    left: str
    operator: ConditionOperator
    right: str | None = None
    on_true: list[str] = Field(default_factory=list)
    on_false: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _right_matches_operator(self) -> ConditionNode:
        if self.operator in UNARY_OPERATORS:
            return self
        if self.right is None:
            raise ValueError(f"operator '{self.operator}' needs a 'right' value")
        return self

    @model_validator(mode="after")
    def _no_fan_out(self) -> ConditionNode:
        # Per-item branching has no sensible answer for "which way did the
        # node go" once items disagree. Fan out first, then compare.
        if self.for_each is not None:
            raise ValueError(
                "a condition cannot use 'for_each' — put the condition inside "
                "the node that fans out, or fan out afterwards"
            )
        return self

    def successors(self) -> list[str]:
        return [*self.next, *self.on_true, *self.on_false]


class AiOutputField(BaseModel):
    """One field the AI node must return.

    Declaring fields rather than a raw JSON schema keeps the editor simple and
    gives downstream nodes something to autocomplete against.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    type: Literal["text", "number", "boolean", "list"] = "text"
    description: str = ""

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not NODE_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "must start with a letter and use only lowercase letters, "
                "digits and underscores"
            )
        return value


class AiNode(NodeBase):
    """Ask a model something and get typed fields back.

    The output contract is the point. A node that returns prose forces the
    next node to parse it; declaring fields means the engine validates the
    shape once and everything downstream can rely on it.
    """

    kind: Literal[FlowNodeKind.AI] = FlowNodeKind.AI

    prompt: str
    output_fields: list[AiOutputField] = Field(
        default_factory=list, max_length=MAX_AI_OUTPUT_FIELDS
    )
    # Bounds a single model call. Separate from the run budget.
    timeout_seconds: float = Field(default=90.0, gt=0.0, le=300.0)

    @field_validator("prompt")
    @classmethod
    def _non_empty_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("output_fields")
    @classmethod
    def _unique_field_names(cls, value: list[AiOutputField]) -> list[AiOutputField]:
        names = [field.name for field in value]
        duplicates = {name for name in names if names.count(name) > 1}
        if duplicates:
            raise ValueError(
                "duplicate output field names: " + ", ".join(sorted(duplicates))
            )
        return value


class HumanNode(NodeBase):
    """Stop and wait for a person to approve or reject.

    The run parks here rather than failing: its status becomes
    AWAITING_DECISION and the node keeps an open row. Answering writes the
    decision onto that row and re-queues the run, which replays the nodes that
    already finished and carries on down the chosen branch. Nothing is held in
    memory in between, so a worker restart costs nothing.

    An empty ``on_reject`` is the plain approval gate: rejecting stops the run
    and marks it failed, because a rejected deploy reading as a clean success
    is exactly the kind of thing nobody notices until it matters. Wire a
    reject branch when a "no" should do something instead.
    """

    kind: Literal[FlowNodeKind.HUMAN] = FlowNodeKind.HUMAN

    question: str = Field(max_length=MAX_QUESTION_LENGTH)
    # Who should answer. Informational — the flow's owner can always decide.
    assignee: str | None = None
    on_approve: list[str] = Field(default_factory=list)
    on_reject: list[str] = Field(default_factory=list)

    @field_validator("question")
    @classmethod
    def _non_empty_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def _no_fan_out(self) -> HumanNode:
        # One question per item would mean one parked run per item, and there
        # is no sane answer for "which branch" once the answers disagree.
        if self.for_each is not None:
            raise ValueError(
                "an approval cannot use 'for_each' — ask once, then fan out"
            )
        return self

    def successors(self) -> list[str]:
        return [*self.next, *self.on_approve, *self.on_reject]


class CodeNode(NodeBase):
    """Run a snippet of Python against the run's data.

    The snippet executes in the sandboxed code interpreter, never in the
    worker. That is not a detail: worker processes hold database credentials,
    connector secrets and the tenant's environment, and a flow is authored in
    a browser by whoever can edit it.

    The snippet sees ``trigger``, ``steps``, ``item`` and ``index`` as plain
    data, and whatever it assigns to ``result`` becomes the node's output.
    ``print`` goes to ``logs`` on the same output, which is usually how you
    find out what the snippet actually saw.
    """

    kind: Literal[FlowNodeKind.CODE] = FlowNodeKind.CODE

    code: str = Field(max_length=MAX_CODE_LENGTH)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=MAX_CODE_TIMEOUT_SECONDS)

    @field_validator("code")
    @classmethod
    def _non_empty_code(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class LoopNode(NodeBase):
    """Cut a list into batches.

    A spec is acyclic, so there is no jumping backwards; looping here means
    handing the next node a manageable slice instead of four hundred items at
    once. Pair it with ``for_each`` on the node that follows:

        loop.over       = "{{ steps.fetch.rows }}"
        loop.batch_size = 25
        send.for_each   = "{{ steps.loop.batches }}"

    ``send`` then runs once per batch with ``{{ item }}`` bound to the 25 rows,
    which is the shape most bulk APIs actually want.
    """

    kind: Literal[FlowNodeKind.LOOP] = FlowNodeKind.LOOP

    over: str
    batch_size: int = Field(default=1, ge=1, le=MAX_FAN_OUT_ITEMS)

    @field_validator("over")
    @classmethod
    def _non_empty_over(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class RetryNode(HttpNode):
    """Call an endpoint over and over until the answer is the one you want.

    Not the same thing as ``retry`` on a node, and the difference is the whole
    reason this exists: the retry policy tries again when a step *raised*,
    while this one tries again when the step *succeeded and said "not yet"*.
    Long jobs behind an API are the common case — you POST, you get a job id,
    and then you sit there asking whether it is done.

    The check walks ``until_path`` through the response body and compares it
    with the same operators a condition uses, so there is one comparison
    vocabulary in the product rather than two.
    """

    kind: Literal[FlowNodeKind.RETRY] = FlowNodeKind.RETRY

    # Dot path into the response body. Empty tests the whole body.
    until_path: str | None = None
    operator: ConditionOperator = "eq"
    value: str | None = None

    max_checks: int = Field(default=10, ge=1, le=MAX_RETRY_CHECKS)
    interval_seconds: float = Field(default=5.0, ge=0.0, le=MAX_RETRY_INTERVAL_SECONDS)
    # Running out of checks is usually a real failure — the job never
    # finished. Turn this off to carry on and branch on `satisfied` instead.
    fail_when_exhausted: bool = True

    @model_validator(mode="after")
    def _value_matches_operator(self) -> RetryNode:
        if self.operator in UNARY_OPERATORS:
            return self
        if self.value is None:
            raise ValueError(f"operator '{self.operator}' needs a 'value'")
        return self

    @model_validator(mode="after")
    def _window_fits_the_budget(self) -> RetryNode:
        window = self.max_checks * self.interval_seconds
        if window > MAX_RETRY_WINDOW_SECONDS:
            raise ValueError(
                f"{self.max_checks} checks {self.interval_seconds:g}s apart "
                f"would wait up to {window:.0f}s, over the "
                f"{MAX_RETRY_WINDOW_SECONDS:.0f}s limit for one step"
            )
        return self


class WebhookNode(NodeBase):
    """POST a payload to an outside system.

    The HTTP node can do this. What it cannot do is prove the delivery came
    from here: this one signs the body with the flow's signing secret and
    sends the signature and a timestamp alongside it, which is what every
    receiver worth integrating with expects to check.

    It also does not fail the run by default. A receiver being down is their
    outage, not a reason to stop an automation that has already done its work.
    """

    kind: Literal[FlowNodeKind.WEBHOOK] = FlowNodeKind.WEBHOOK

    url: str
    # Rendered through the expression layer, so a delivery can be assembled
    # from upstream output without a transform node in front of it.
    payload: Any = None
    headers: dict[str, str] = Field(default_factory=dict)

    timeout_seconds: float = Field(default=30.0, gt=0.0, le=MAX_HTTP_TIMEOUT_SECONDS)
    fail_on_error_status: bool = False

    @field_validator("url")
    @classmethod
    def _non_empty_url(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class DelayNode(NodeBase):
    """Wait, then carry on.

    Short waits sleep where they stand. Anything longer parks the run — its
    status becomes AWAITING_DELAY, the node keeps an open row, and a sweep
    re-queues it when it comes due — so "follow up tomorrow" costs nothing
    while it waits and survives a deploy in the middle.

    The threshold is 60 seconds, and it is a threshold rather than a setting
    because the trade is fixed: parking costs one sweep tick, so below a
    minute the park is slower than the wait it replaces.
    """

    kind: Literal[FlowNodeKind.DELAY] = FlowNodeKind.DELAY

    seconds: float = Field(default=60.0, ge=0.0, le=MAX_DELAY_SECONDS)

    @model_validator(mode="after")
    def _no_fan_out(self) -> DelayNode:
        # Waiting once per item means the same wall clock spent N times over,
        # which is never what anybody means. Wait once, then fan out.
        if self.for_each is not None:
            raise ValueError("a delay cannot use 'for_each' — wait once, then fan out")
        return self

    def parks_the_run(self) -> bool:
        """Whether this delay is long enough to park rather than sleep."""
        return self.seconds > INLINE_DELAY_SECONDS


class ScheduleNode(NodeBase):
    """Wait until the next time a cron expression comes round.

    The sibling of a delay: that one waits for a duration, this one waits for
    a moment. "Finish the work now, send the digest at nine tomorrow" is the
    shape, and a duration cannot express it without the author doing the
    arithmetic themselves every time.

    It parks the run exactly as a delay does, and for the same reason. A next
    occurrence inside a minute sleeps instead, so the two kinds behave the
    same way at the same threshold.

    Cron is read in UTC, matching the schedule triggers.
    """

    kind: Literal[FlowNodeKind.SCHEDULE] = FlowNodeKind.SCHEDULE

    # 5-field cron, the same grammar a schedule trigger takes.
    cron: str

    @field_validator("cron")
    @classmethod
    def _non_empty_cron(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def _no_fan_out(self) -> ScheduleNode:
        # One moment arrives once, however many items are in flight.
        if self.for_each is not None:
            raise ValueError(
                "a schedule cannot use 'for_each' — wait once, then fan out"
            )
        return self


class MergeNode(NodeBase):
    """Bring the output of several earlier steps back together.

    A graph can already fan out and join — a node runs as soon as any
    predecessor hands control to it. What it could not do is see what the
    other branch produced, and that is what this is for: two calls in
    parallel, one step that uses both.

    ``sources`` names which earlier steps to combine. It is not adjacency —
    those steps already name this one in their ``next`` — it is a choice among
    what has run, so a node with three inputs can merge two of them.

    A source that did not run contributes nothing rather than failing. That is
    the normal case after a condition: one branch ran, the other was skipped,
    and the merge is exactly where you find out which.
    """

    kind: Literal[FlowNodeKind.MERGE] = FlowNodeKind.MERGE

    sources: list[str] = Field(min_length=2, max_length=MAX_MERGE_SOURCES)
    # ``combine`` keys each source's output by its id; ``append`` joins the
    # sources' lists into one.
    mode: Literal["combine", "append"] = "combine"

    @field_validator("sources")
    @classmethod
    def _unique_sources(cls, value: list[str]) -> list[str]:
        duplicates = {name for name in value if value.count(name) > 1}
        if duplicates:
            raise ValueError("duplicate sources: " + ", ".join(sorted(duplicates)))
        return value

    @model_validator(mode="after")
    def _no_fan_out(self) -> MergeNode:
        # The sources each produced one output, so there is nothing to fan
        # this over. Merge first, then fan out over the result.
        if self.for_each is not None:
            raise ValueError(
                "a merge cannot use 'for_each' — merge first, then fan out"
            )
        return self


class FilterNode(NodeBase):
    """Keep the items of a list that match a comparison.

    The condition node picks a branch for the whole run; this one picks
    elements. Pair it with ``for_each`` on whatever comes next and you have
    "do this to the ones that matter", which is most of what a flow over a
    list is for.

    ``left`` is evaluated once per element with ``{{ item }}`` and
    ``{{ index }}`` bound, so a filter can compare an element against
    something a previous step produced rather than only against a constant.
    """

    kind: Literal[FlowNodeKind.FILTER] = FlowNodeKind.FILTER

    over: str
    left: str
    operator: ConditionOperator = "eq"
    right: str | None = None

    @field_validator("over", "left")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def _right_matches_operator(self) -> FilterNode:
        if self.operator in UNARY_OPERATORS:
            return self
        if self.right is None:
            raise ValueError(f"operator '{self.operator}' needs a 'right' value")
        return self


FlowNode = Annotated[
    HttpNode
    | TransformNode
    | ConditionNode
    | AiNode
    | HumanNode
    | CodeNode
    | LoopNode
    | RetryNode
    | WebhookNode
    | DelayNode
    | FilterNode
    | ScheduleNode
    | MergeNode,
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# The spec
# ---------------------------------------------------------------------------


class FlowSpec(BaseModel):
    """A validated, executable flow.

    Parsing a spec guarantees the engine four things: ids are unique, every
    reference resolves, there are no cycles, and the entry node exists. Nodes
    that nothing reaches are allowed — the editor creates one every time
    someone drops a node on the canvas, and failing autosave over it would be
    obnoxious. The engine simply never runs them.
    """

    model_config = ConfigDict(extra="forbid")

    spec_version: Literal[1] = 1
    start: str
    nodes: list[FlowNode] = Field(min_length=1, max_length=MAX_NODES_PER_FLOW)

    @model_validator(mode="after")
    def _check_graph(self) -> FlowSpec:
        by_id: dict[str, Any] = {}
        for node in self.nodes:
            if node.id in by_id:
                raise ValueError(f"duplicate node id: {node.id}")
            by_id[node.id] = node

        if self.start not in by_id:
            raise ValueError(f"start node '{self.start}' is not defined")

        for node in self.nodes:
            for target in node.successors():
                if target not in by_id:
                    raise ValueError(
                        f"node '{node.id}' points at undefined node '{target}'"
                    )
                if target == node.id:
                    raise ValueError(f"node '{node.id}' points at itself")

        _reject_cycles(by_id)
        _check_merge_sources(by_id)
        return self

    def node_map(self) -> dict[str, Any]:
        """Nodes keyed by id, in declaration order."""
        return {node.id: node for node in self.nodes}

    def reachable_ids(self) -> set[str]:
        """Ids the engine can actually arrive at from ``start``."""
        by_id = self.node_map()
        seen: set[str] = set()
        stack = [self.start]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(by_id[current].successors())
        return seen


def _check_merge_sources(by_id: dict[str, Any]) -> None:
    """Every merge source must be a step that leads to the merge.

    Checking ancestry rather than mere existence is what makes the node
    honest: a source that does not lead here has either not run yet or never
    will, so combining it would be reading a step's output before it has one.
    It also catches the common slip of naming the sources and forgetting to
    wire them.
    """
    for node in by_id.values():
        if node.kind is not FlowNodeKind.MERGE:
            continue
        for source in node.sources:
            if source not in by_id:
                raise ValueError(f"node '{node.id}' merges undefined node '{source}'")
            if source == node.id:
                raise ValueError(f"node '{node.id}' merges itself")
            if node.id not in _descendants(source, by_id):
                raise ValueError(
                    f"node '{node.id}' merges '{source}', which does not lead "
                    "to it — connect them, or merge something that does"
                )


def _descendants(start: str, by_id: dict[str, Any]) -> set[str]:
    """Every node reachable by following successors from ``start``."""
    seen: set[str] = set()
    stack = list(by_id[start].successors())
    while stack:
        current = stack.pop()
        if current in seen or current not in by_id:
            continue
        seen.add(current)
        stack.extend(by_id[current].successors())
    return seen


def _reject_cycles(by_id: dict[str, Any]) -> None:
    """Depth-first search for a back edge.

    Iterative rather than recursive so a wide spec cannot blow the stack, and
    the error names the node that closes the loop because "cycle detected" on
    its own is useless when you are staring at forty boxes.
    """
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(by_id, WHITE)

    for root in by_id:
        if colour[root] != WHITE:
            continue
        stack: list[tuple[str, list[str]]] = [(root, list(by_id[root].successors()))]
        colour[root] = GREY
        while stack:
            node_id, pending = stack[-1]
            if not pending:
                colour[node_id] = BLACK
                stack.pop()
                continue
            nxt = pending.pop()
            if colour[nxt] == GREY:
                raise ValueError(f"nodes form a cycle through '{nxt}'")
            if colour[nxt] == WHITE:
                colour[nxt] = GREY
                stack.append((nxt, list(by_id[nxt].successors())))


def parse_spec(raw: dict[str, Any]) -> FlowSpec:
    """Validate a stored or submitted spec.

    Raises:
        SpecError: with a message meant for the person editing the flow.
    """
    try:
        return FlowSpec.model_validate(raw)
    except ValidationError as exc:
        raise SpecError(_readable_validation_error(exc)) from exc
    except ValueError as exc:
        raise SpecError(str(exc)) from exc


def _readable_validation_error(exc: ValidationError) -> str:
    """Flatten pydantic's report into something an editor can show.

    Pydantic's default rendering carries a docs URL and the offending input on
    every line, which is noise in a toast. Keep the location and the message.
    """
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(piece) for piece in error["loc"] if piece != "nodes")
        message = error["msg"].removeprefix("Value error, ")
        parts.append(f"{location}: {message}" if location else message)
    # Duplicates are common when a discriminated union reports per-variant.
    seen: list[str] = []
    for part in parts:
        if part not in seen:
            seen.append(part)
    return "; ".join(seen)
