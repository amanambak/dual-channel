from functools import lru_cache

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.nodes import build_turn_nodes
from app.graph.state import TurnState
from app.llm.service import LLMService


@lru_cache(maxsize=1)
def get_turn_graph():
    llm = LLMService()
    nodes = build_turn_nodes(llm)

    graph = StateGraph(TurnState)
    graph.add_node("extract_schema", nodes["extract_schema"])
    graph.add_node("generate_response", nodes["generate_response"])
    graph.add_conditional_edges(
        START,
        lambda state: "extract_schema" if state.get("should_extract") else (
            "generate_response" if state.get("should_trigger") else END
        ),
        ["extract_schema", "generate_response", END],
    )
    graph.add_conditional_edges(
        "extract_schema",
        lambda state: "generate_response" if state.get("should_trigger") else END,
        ["generate_response", END],
    )
    graph.add_edge("generate_response", END)
    return graph.compile(checkpointer=MemorySaver())
