from langgraph.graph import StateGraph, START, END
from app.agent.state import AgentState
from app.agent.nodes import router_node, small_talk_node, human_handoff_node, rag_node

def route_decision(state: AgentState):
    """
    Conditional Edge Logic.
    Reads the 'intent' from state and returns the next node name.
    """
    intent = state.get("intent")
    if intent == "small_talk":
        return "small_talk"
    elif intent == "human":
        return "human_handoff"
    else:
        return "rag"

def build_graph():
    """Compiles and returns the LangGraph executable."""
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("router", router_node)
    workflow.add_node("small_talk", small_talk_node)
    workflow.add_node("human_handoff", human_handoff_node)
    workflow.add_node("rag", rag_node)

    # Add Main Edges
    workflow.add_edge(START, "router")

    # Add Conditional Edges
    workflow.add_conditional_edges(
        "router",
        route_decision,
        {
            "small_talk": "small_talk",
            "human_handoff": "human_handoff",
            "rag": "rag"
        }
    )

    # Common Exit
    workflow.add_edge("small_talk", END)
    workflow.add_edge("human_handoff", END)
    workflow.add_edge("rag", END)

    return workflow.compile()

# Global instance for import
agent_app = build_graph()
