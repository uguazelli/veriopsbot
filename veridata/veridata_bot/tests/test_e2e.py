import pytest
import uuid
from sqlalchemy import select
from app.models import Client, Subscription, ServiceConfig
from app.core.config import settings
from app.bot.engine import handle_chatwoot_response

@pytest.mark.asyncio
async def test_bot_webhook_flow(client, db_session, mock_chatwoot_response):
    # 1. Setup Data
    unique_slug = f"test-bot-{uuid.uuid4().hex[:8]}"

    # Create Client
    new_client = Client(
        slug=unique_slug,
        name="Test Bot Client",
        is_active=True
    )
    db_session.add(new_client)
    await db_session.flush()

    # Create Subscription (with quota)
    # 1000 message limit
    sub = Subscription(
        client_id=new_client.id,
        quota_limit=1000,
        usage_count=0
    )
    db_session.add(sub)

    # Create ServiceConfig (RAG and Chatwoot)
    # Using real RAG URL from settings or env
    combined_config = {
        "rag": {
            "base_url": "http://127.0.0.1:8000",
            "tenant_id": "test_tenant",
            "api_key": settings.rag_api_key,
            "google_sheets_url": ""
        },
        "chatwoot": {
            "api_key": "mock_token",
            "base_url": "http://mock.chatwoot",
            "account_id": 1,
            "inbox_id": 1
        }
    }

    service_config = ServiceConfig(
        client_id=new_client.id,
        config=combined_config
    )

    db_session.add(service_config)
    await db_session.commit()

    # 2. Prepare Payload
    # Simulating a user message in Chatwoot
    conversation_id = 12345
    webhook_payload = {
        "event": "message_created",
        "message_type": "incoming",
        "content": "Hello, are you a bot?",
        "conversation": {
            "id": conversation_id,
            "status": "pending"
        },
        "sender": {
            "id": 999,
            "name": "Test User",
            "email": "test@example.com"
        },
        "account": {
            "id": 1
        }
    }

    # 3. Trigger Webhook
    response = await client.post(f"/bot/chatwoot/{unique_slug}", json=webhook_payload)

    assert response.status_code == 200
    assert response.json() == {"status": "processing_started"}

    # 4. Wait for background processing
    # Since we are using TestClient, background tasks might not run automatically
    # if we don't handle them or if we are using AsyncClient which doesn't block.
    # However, for integration tests with `async def`, we might need to invoke logic directly
    # OR rely on a small sleep if the component is truly async in background.
    # But wait, `process_bot_event` is called in `run_bot_bg`.
    # In a real environment, FastAPI's BackgroundTasks run after the response.
    # We can manually trigger the logic to ensure we test the Engine, OR we can wait.
    # Let's try to manually import and run the engine logic to be deterministic,
    # OR we can update the test to call process_bot_event directly if we want to test the logic specifically.
    # BUT, the request asked for "automatic test" hitting the endpoint.
    # We'll rely on the fact that we can call the function directly for deterministic testing
    # OR simple waiting. For correctness, let's call the Logic directly using the same payload
    # to catch exceptions immediately, effectively integration testing the SERVICE layer.

    from app.bot.engine import process_bot_event

    # Pass the session we are part of
    result = await process_bot_event(unique_slug, webhook_payload, db_session)

    assert result["status"] == "processed"

    # 5. Verify Mock Call
    # Ensure our bot tried to send a response back
    assert mock_chatwoot_response.called
    args, _ = mock_chatwoot_response.call_args
    # args: (conversation_id, answer, requires_human, config)

    called_conversation_id = args[0]
    answer = args[1]

    assert str(called_conversation_id) == str(conversation_id)
    assert answer is not None
    assert len(answer) > 0
