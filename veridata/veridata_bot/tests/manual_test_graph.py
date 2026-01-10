import asyncio
import sys
import os

# Add the project root to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langchain_core.messages import HumanMessage
from app.agent.graph import agent_app

async def test_all_paths():
    scenarios = [
        {"input": "Hello there!", "expected_intent": "small_talk"},
        {"input": "I need a human agent.", "expected_intent": "human_handoff"},
        {"input": "What is the capital of France?", "expected_intent": "rag"}, # Simple RAG
        {"input": "Compare the pricing plans for the Enterprise vs Pro subscription.", "expected_intent": "rag", "check_pricing": True, "min_complexity": 7} # Complex + Pricing
    ]

    for scenario in scenarios:
        print(f"\n--- Testing Input: '{scenario['input']}' ---")
        state = {
            "messages": [HumanMessage(content=scenario["input"])],
            "tenant_id": "00000000-0000-0000-0000-000000000000", # Dummy Valid UUID
            "session_id": None
        }
        try:
            result = await agent_app.ainvoke(state)
            last_msg = result["messages"][-1].content
            print(f"Agent Reply: {last_msg}")

            # Simple keyword check (heuristic)
            if scenario["expected_intent"] == "small_talk":
                if "Veribot" in last_msg or "Hello" in last_msg or "Hi" in last_msg:
                    print("✅ Small Talk Logic: PASSED")
                else:
                    print("❌ Small Talk Logic: FAILED (Check Router/LLM)")

            elif scenario["expected_intent"] == "human_handoff":
                if "support agent" in last_msg or "human" in last_msg.lower():
                    print("✅ Human Handoff Logic: PASSED")
                else:
                    print("❌ Human Handoff Logic: FAILED")

            elif scenario["expected_intent"] == "rag":
                # For RAG, we expect either a real answer or our mock error message if connection fails
                # Since we don't have a real RAG server running reachable from this script (unless localhost:8000 is up)
                # We mainly check that it didn't crash and tried to provide info.
                print("✅ RAG Logic: Executed (Response received)")

                # Check extras if needed
                if scenario.get("check_pricing"):
                    # We need to peek into the state, but 'ainvoke' returns the FINAL state.
                    # 'result' IS the final state.
                    pricing = result.get("pricing_intent", False)
                    complexity = result.get("complexity_score", 0)
                    print(f"   Pricing Detected: {pricing}")
                    print(f"   Complexity Score: {complexity}")

                    if pricing and complexity >= scenario["min_complexity"]:
                        print("✅ Complex Pricing Logic: PASSED")
                    else:
                        print("❌ Complex Pricing Logic: FAILED")

        except Exception as e:
            print(f"❌ Execution FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(test_all_paths())
