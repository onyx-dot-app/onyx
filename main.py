from operator import add
from typing import Annotated
from typing import TypedDict

from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph
from langgraph.types import Send


class MainState(TypedDict):
    foo: Annotated[str, add]
    bar: str


class SubState(TypedDict):
    foo: str
    bar: str


class SubStateInput(TypedDict):
    foo: str
    num: int


class SubStateOutput(TypedDict):
    foo: str


def node_1(state: MainState):
    print(f"node_1: {state}")
    return {
        "foo": " name",
        "bar": "bar",
    }


def node_2(state: SubStateInput):
    print(f"node_2: {state}")
    return SubState(
        foo=" more foo" + str(state["num"]),
        bar="barty hard" + str(state["num"]),
    )


def node_3(state: SubState):
    print(f"node_3: {state}")
    return SubStateOutput(
        foo=state["foo"] + " more foo",
    )


def node_4(state: SubStateOutput):
    print(f"node_4: {state}")
    return MainState(
        foo="",
    )
    return MainState(
        foo=state["foo"],
    )


def send_to_sub_graph(state: MainState):
    return [
        Send(
            "sub_graph",
            SubStateInput(
                foo=state["foo"],
                num=num,
            ),
        )
        for num in range(3)
    ]


def build_sub_graph():
    sub_graph = StateGraph(
        state_schema=SubState,
        input=SubStateInput,
        output=SubStateOutput,
    )
    sub_graph.add_node(node="node_2", action=node_2)
    sub_graph.add_node(node="node_3", action=node_3)
    sub_graph.add_edge(start_key=START, end_key="node_2")
    sub_graph.add_edge(start_key="node_2", end_key="node_3")
    sub_graph.add_edge(start_key="node_3", end_key=END)
    return sub_graph


def build_main_graph():
    graph = StateGraph(
        state_schema=MainState,
    )
    graph.add_node(node="node_1", action=node_1)

    sub_graph = build_sub_graph().compile()
    graph.add_node(node="sub_graph", action=sub_graph)
    graph.add_node(node="node_4", action=node_4)
    graph.add_edge(start_key=START, end_key="node_1")
    # graph.add_edge(start_key="node_1", end_key="sub_graph")
    graph.add_conditional_edges(source="node_1", path=send_to_sub_graph)
    graph.add_edge(start_key="sub_graph", end_key="node_4")
    graph.add_edge(start_key="node_4", end_key=END)
    return graph


graph = build_main_graph().compile()
output = graph.invoke(
    {
        "foo": "",
    },
)
print(output)
