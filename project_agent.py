from __future__ import annotations

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from prompt import PROMPT

load_dotenv()


@tool
def get_data():
    """Get the current device/project data."""
    return """
Project Name: Misso Robotic System
Client: Meril Life Sciences
Device ID: DHF-RBT-042
Status: Active Development

Current Tasks:
- Integrating LiDAR-based navigation
- Optimizing voice command pipeline
- Testing obstacle avoidance module
- Improving battery monitoring dashboard

Recent Metrics:
- Uptime: 98.7%
- Battery Health: 94%
- Navigation Accuracy: 96.2%
- Voice Command Success Rate: 92.8%

Last Update:
The robotics team completed indoor mapping tests in the manufacturing unit.
The system successfully navigated 1.8 km of test routes and identified
37 simulated obstacles with a 96% detection rate.
"""


agent_graph = create_agent(
    system_prompt=(
        PROMPT
        + "\nTOOL RULE: Call get_data ONLY when the user asks about the specific project, device, metrics, tasks, status, or client. For all other questions (greetings, general knowledge, anything not project-specific) answer directly from your own knowledge."
        + "\nNever make up project-specific values — those must always come from get_data. If the tool data doesn't contain the answer, say 'I don't have that information.'"
        + "\nRULES: Reply in ONE short spoken sentence only. No lists, no newlines, no formatting. Voice interface only."
    ),
    model=ChatOpenAI(model="gpt-4o-mini", temperature=0.5, max_tokens=50),
    tools=[get_data],
)

# Filter ToolMessages so raw tool data never reaches TTS
_raw_astream = agent_graph.astream

async def _filtered_astream(*args, **kwargs):
    async for item in _raw_astream(*args, **kwargs):
        msg = item[0] if isinstance(item, tuple) else item
        if isinstance(msg, ToolMessage):
            print(f"  [FILTER] blocked ToolMessage: {str(msg.content)[:60]!r}", flush=True)
            continue
        yield item

agent_graph.astream = _filtered_astream
