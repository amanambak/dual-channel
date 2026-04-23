from collections.abc import AsyncIterator

from app.graph.factory import get_turn_graph
from app.graph.state import TurnState


class TurnGraphService:
    def __init__(self) -> None:
        self.graph = get_turn_graph()

    async def stream_turn(
        self, state: TurnState, thread_id: str
    ) -> AsyncIterator[dict]:
        config = {"configurable": {"thread_id": thread_id}}
        async for chunk in self.graph.astream(
            state,
            config=config,
            stream_mode=["updates", "custom"],
            version="v2",
        ):
            yield chunk

