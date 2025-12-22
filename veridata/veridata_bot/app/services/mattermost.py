import httpx

class MattermostService:
    def __init__(self):
        pass

    async def send_message(self, server_url: str, bot_token: str, channel_id: str, text: str = "", username: str = None, props: dict = None, attachments: list = None):
        """
        Sends a message to a Mattermost channel.
        """
        url = f"{server_url}/api/v4/posts"
        headers = {
            "Authorization": f"Bearer {bot_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "channel_id": channel_id,
            "message": text
        }

        # Initialize props
        if props:
            payload["props"] = props.copy()
        else:
            payload["props"] = {}

        # If username override is provided
        if username:
            payload["props"]["override_username"] = username

        # Attachments
        if attachments:
            payload["props"]["attachments"] = attachments

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
            except Exception as e:
                print(f"Failed to send Mattermost message: {e}")
