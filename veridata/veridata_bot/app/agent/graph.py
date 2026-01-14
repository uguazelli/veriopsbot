from langgraph.graph import END, START, StateGraph

from app.agent.nodes import grader_node, human_handoff_node, rag_node, rewrite_node, router_node
from app.agent.state import AgentState


# ==================================================================================
# CONDITIONAL EDGE LOGIC (The Router's Brain)
# ==================================================================================
def route_decision(state: AgentState):
    """Called AFTER the 'router' node.
    It checks the 'intent' field stored in the state (RAG vs HUMAN)
    and tells the graph which node to visit next.
    """
    intent = state.get("intent")
    if intent == "human":
        # If user wants a human, go to Handoff Node
        return "human_handoff"
    else:
        # Defaults to RAG (even for small talk, which is RAG with complexity=1)
        return "rag"


def grade_decision(state: AgentState):
    """Decides whether to accept the RAG answer or retry."""
    grading_reason = state.get("grading_reason", "")
    retry_count = state.get("retry_count", 0)

    # Parse Score
    if "SCORE: 1" in grading_reason:
        return "end"

    # It's SCORE: 0 (Bad)
    if retry_count < 2:  # Allow 2 retries
        return "rewrite"
    else:
        # Too many retries, give up (or handoff)
        # For now, let's just end (sending the "I don't know" or bad answer)
        # OR better, route to handoff?
        # Let's route to handoff to be helpful.
        return "human_handoff"


# ==================================================================================
# BUILD THE GRAPH (The Workflow Definition)
# ==================================================================================
def build_graph():
    """Compiles and returns the LangGraph executable."""
    workflow = StateGraph(AgentState)

    # ------------------------------------------------------------------
    # 1. ADD NODES (The Workers)
    # ------------------------------------------------------------------
    # 'router': First step. Uses LLM to classify intent.
    workflow.add_node("router", router_node)

    # 'human_handoff': If user wants human, this node crafts the handover message.
    workflow.add_node("human_handoff", human_handoff_node)

    # 'rag': The main workhorse. Calls vector DB to answer questions.
    workflow.add_node("rag", rag_node)

    # 'grader': Evals the RAG output
    workflow.add_node("grader", grader_node)

    # 'rewrite': Optimizes the query
    workflow.add_node("rewrite", rewrite_node)

    # ------------------------------------------------------------------
    # 2. DEFINES EDGES (The Connections)
    # ------------------------------------------------------------------
    # Start -> Router
    workflow.add_edge(START, "router")

    # Router -> (Conditional) -> Handoff OR RAG
    workflow.add_conditional_edges("router", route_decision, {"human_handoff": "human_handoff", "rag": "rag"})

    # RAG -> Grader (Always grade RAG output)
    workflow.add_edge("rag", "grader")

    # Grader -> (Conditional) -> Rewrite OR Handoff OR End
    workflow.add_conditional_edges(
        "grader",
        grade_decision,
        {
            "rewrite": "rewrite",
            "human_handoff": "human_handoff",
            "end": END,
        },
    )

    # Rewrite -> RAG (Loop back)
    workflow.add_edge("rewrite", "rag")

    # ------------------------------------------------------------------
    # 3. DEFINE EXITS
    # ------------------------------------------------------------------
    # Handoff leads to End
    workflow.add_edge("human_handoff", END)
    # RAG no longer goes to END directly, it goes to Grader

    return workflow.compile()


# Global instance for import
agent_app = build_graph()
