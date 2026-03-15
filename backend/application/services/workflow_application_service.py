
from typing import AsyncGenerator

from backend.agents.base.agent_input import AgentInput
from backend.agents.base.stream_chunk import StreamChunk
from backend.workflows.workflow_executor import WorkflowExecutor


class WorkflowApplicationService:
    def __init__(self, workflow_executor: WorkflowExecutor | None = None):
        self.workflow_executor = workflow_executor or WorkflowExecutor()

    async def execute_stream(self, agent_input: AgentInput) -> AsyncGenerator[StreamChunk, None]:
        async for chunk in self.workflow_executor.execute_workflow(agent_input):
            yield chunk

