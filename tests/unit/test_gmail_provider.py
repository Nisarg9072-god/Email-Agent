"""Tests for Gmail body extraction helpers."""

from app.email.gmail_provider import GmailEmailProvider


class TestGmailBodyExtraction:
    def test_html_to_text_strips_tags(self):
        html = "<p>Hi NovaAI team</p><p>Pricing for <b>NovaSupport AI</b></p>"
        text = GmailEmailProvider._html_to_text(html)
        assert "NovaSupport AI" in text
        assert "<p>" not in text

    def test_extract_body_from_nested_html_part(self):
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {
                        "data": "PGh0bWw+SGkgTm92YUAIHRlYW08L2h0bWw+",
                    },
                }
            ],
        }
        import base64

        html = "<html>Hi NovaAI team</html>"
        payload["parts"][0]["body"]["data"] = base64.urlsafe_b64encode(
            html.encode()
        ).decode()
        body = GmailEmailProvider._extract_body(None, "msg-1", payload)
        assert "NovaAI team" in body
