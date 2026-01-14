import pytest
from unittest.mock import AsyncMock, MagicMock
from app.agent.graph import agent_app
from app.agent.state import AgentState
from langchain_core.messages import HumanMessage, AIMessage

@pytest.mark.asyncio
async def test_self_correction_loop(mocker):
    # Mock the LLM calls in nodes.py
    # We need to mock ChatGoogleGenerativeAI inside nodes.py

    # Mock Grader to return SCORE: 0 first, then SCORE: 1
    mock_grader_response_bad = MagicMock()
    mock_grader_response_bad.content = '{"score": 0, "reason": "Bad answer"}'

    mock_grader_response_good = MagicMock()
    mock_grader_response_good.content = '{"score": 1, "reason": "Good answer"}'

    # Mock Rewrite to return a new query
    mock_rewrite_response = MagicMock()
    mock_rewrite_response.content = "Better Query"

    # Mock Router to return "rag"
    mock_router_response = MagicMock()
    mock_router_response.content = '{"requires_rag": true}'

    # We need to mock the `ainvoke` method of the LLM class used in nodes.py
    # This is tricky because the class is instantiated inside the node function.
    # Better to mock `app.agent.nodes.ChatGoogleGenerativeAI`

    MockLLM = mocker.patch("app.agent.nodes.ChatGoogleGenerativeAI")

    # We need to control the side_effect to simulate the sequence:
    # 1. Router -> RAG
    # 2. RAG -> Grader (Bad)
    # 3. Grader -> Rewrite
    # 4. Rewrite -> RAG
    # 5. RAG -> Grader (Good)
    # 6. Grader -> End

    # The Router uses 'json' output.
    # The Grader uses 'json' output.
    # The Rewrite uses string output.

    # It's hard to distinguish WHICH node is calling ainvoke just by the mock return values sequence if they use the same class.
    # However, we can use `side_effect` checking the input messages, OR just simple sequence if deterministic.
    # Sequence:
    # 1. Router (User Msg)
    # 2. Grader (RAG Msg 1) -> Returns 0
    # 3. Rewrite (User Msg + Reason) -> Returns "New Query"
    # 4. Grader (RAG Msg 2) -> Returns 1

    # Note: RAG node does NOT use the LLM (it uses RagClient). We need to mock RAG client too.

    mock_rag_client = mocker.patch("app.agent.nodes.RagClient")
    mock_rag_instance = mock_rag_client.return_value
    mock_rag_instance.query = AsyncMock(side_effect=[
        {"answer": "Bad Answer", "requires_human": False},
        {"answer": "Good Answer", "requires_human": False},
    ])

    mock_llm_instance = MockLLM.return_value
    mock_llm_instance.ainvoke = AsyncMock(side_effect=[
        mock_router_response,       # Router
        mock_grader_response_bad,   # Grader 1
        mock_rewrite_response,      # Rewrite
        mock_grader_response_good   # Grader 2
    ])

    initial_state = {
        "messages": [HumanMessage(content="test question")],
        "tenant_id": "t",
        "session_id": "s",
        "google_sheets_url": ""
    }

    # Run the graph
    result = await agent_app.ainvoke(initial_state)

    # Verify we looped
    # The result state should have multiple messages
    # [User, RAG(Bad), User(Rewritten), RAG(Good)]
    # Note: Rewrite node appends a HumanMessage.

    assert len(result["messages"]) >= 4
    assert result["messages"][-1].content == "Good Answer"

    # Check grading reason in final state
    assert "SCORE: 1" in result["grading_reason"]

    # Check retry count
    assert result.get("retry_count", 0) == 1
