from typing import Any, Dict


class ConversationFormatter:
    def __init__(self, summary_data: Dict[str, Any]):
        self.data = summary_data
        # Standardize data access
        self.ai_summary = summary_data.get("ai_summary") or summary_data.get("summary", "No summary provided")
        self.start = summary_data.get("conversation_start", "N/A")
        self.end = summary_data.get("conversation_end", "N/A")
        self.language = summary_data.get("detected_language") or summary_data.get("language", "N/A")
        self.client_desc = summary_data.get("client_description", "N/A")

        # Analysis fields
        self.intent = summary_data.get("purchase_intent", "N/A")
        self.urgency = summary_data.get("urgency_level", "N/A")
        self.sentiment = summary_data.get("sentiment_score") or summary_data.get("sentiment", "N/A")
        self.budget = summary_data.get("detected_budget") or "N/A"

    def to_markdown(self) -> str:
        return (
            f"### AI Conversation Summary 🤖\n\n"
            f"**Period**: {self.start} - {self.end}\n"
            f"**Language**: {self.language}\n\n"
            f"**Summary**: {self.ai_summary}\n\n"
            f"**Client Profile**: {self.client_desc}\n\n"
            f"**Analysis**:\n"
            f"- Intent: {self.intent}\n"
            f"- Urgency: {self.urgency}\n"
            f"- Sentiment: {self.sentiment}\n"
            f"- Budget: {self.budget}"
        )

    def to_html(self) -> str:
        return (
            f"<div style='font-family: sans-serif; color: #33475b;'>"
            f"   <h3 style='margin-top: 0; color: #0091ae;'>🤖 Veridata Bot Summary</h3>"
            f"   <hr>"
            f"   <p><b>📅 Period:</b> {self.start} - {self.end}</p>"
            f"   <p><b>🗣️ Language:</b> {self.language}</p>"
            f"   <br>"
            f"   <p><b>📝 Summary:</b></p>"
            f"   <div style='background-color: #f5f8fa; padding: 12px; border-left: 4px solid #0091ae; border-radius: 4px;'>"
            f"      {self.ai_summary.replace(chr(10), '<br>')}"
            f"   </div>"
            f"   <br>"
            f"   <p><b>👤 Client Profile:</b><br>{self.client_desc}</p>"
            f"   <br>"
            f"   <p><b>📊 Analysis:</b></p>"
            f"   <ul style='list-style-type: circle;'>"
            f"       <li><b>Intent:</b> {self.intent}</li>"
            f"       <li><b>Urgency:</b> {self.urgency}</li>"
            f"       <li><b>Sentiment:</b> {self.sentiment}</li>"
            f"       <li><b>Budget:</b> {self.budget}</li>"
            f"   </ul>"
            f"</div>"
        )
