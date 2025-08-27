# src/block_kits/block_kit.py
# -----------------------------------------------------------------------------
# Slack Block Kit builders used across flows:
#  - LLM suggestion/answer blocks (+ link hints)
#  - Feedback buttons (positive/negative) for message & thread
#  - Follow-up prompts & delay messages
#  - HelpCentral ticket CTA & confirmation message
#  - Outage banner
# -----------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import re
from typing import Any, Dict, List, Optional


# ----------------------------- helpers -------------------------------------- #

HTTP_LINK_RE = re.compile(r"https?://[^\s)>\]]+", flags=re.IGNORECASE)


def _mk_section(text: str) -> Dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _mk_button(text: str, action_id: str, style: Optional[str] = None, value: str = "value") -> Dict[str, Any]:
    btn: Dict[str, Any] = {
        "type": "button",
        "text": {"type": "plain_text", "text": text, "emoji": True},
        "value": value,
        "action_id": action_id,
    }
    if style:
        btn["style"] = style
    return btn


def _divider() -> Dict[str, Any]:
    return {"type": "divider"}


# -------------------------- main answer builder ----------------------------- #

@dataclass
class BlockKit:
    """
    Builder for message-level blocks used by the bot.

    Attributes seen in screenshots:
      - thread     : ts of the message thread (if any)
      - question   : user's query text
      - user_id    : Slack user id
      - block_body : pre-existing blocks to update (optional)
      - channel_id : channel id (used by caller, not here)
      - additional_details: extra context for the LLM or routing
      - bot_id     : bot's user id (for mentions in follow-ups)
      - llm_answer : answer text from LLM (optional, set by caller)
      - llm_link   : link(s) extracted from the LLM answer (optional)
      - channel_name: computed routing name (e.g., help-gcp-apple)
    """

    thread: Optional[str] = None
    question: Optional[str] = None
    user_id: Optional[str] = None
    block_body: Optional[List[Dict[str, Any]]] = None
    channel_id: Optional[str] = None
    additional_details: Optional[str] = None
    bot_id: Optional[str] = None

    # runtime fields
    llm_answer: Optional[str] = None
    llm_link: Optional[str] = None
    channel_name: Optional[str] = None

    # ----------------------- routing (name → pretty) ------------------------ #
    def set_channel_name(self, raw: str) -> None:
        """Normalize a few well-known routes from your screenshots."""
        mapping = {
            "help-gcp-apple": "GCP",
            "help-aws-apple": "AWS",
            "help-oci-apple": "OCI",
            "help-icloud-apple": "iCloud",
            "help-alicloud": "Alicloud",
            "help-linux-found": "Linux Foundation",
            "help-rubix": "Rubix",
            "help-spinclou": "Spincloud",
            "Rubix": "Rubix",
            "GCP": "GCP",
            "AWS": "AWS",
            "OCI": "OCI",
            "Alicloud": "Alicloud",
        }
        self.channel_name = mapping.get(raw, raw or "General")

    # ---------------------- extraction & utilities -------------------------- #
    @staticmethod
    def extract_links(text: str) -> List[str]:
        if not text:
            return []
        return HTTP_LINK_RE.findall(text)

    @staticmethod
    def _link_hint_blocks(links: List[str]) -> List[Dict[str, Any]]:
        """A tiny hint section for one or more helpful links."""
        if not links:
            return []
        # Show first 1–3 links to keep it compact
        items = links[:3]
        bullets = "\n".join(f"• {u}" for u in items)
        return [
            _mk_section(f"*The following link(s) might help you:*\n{bullets}")
        ]

    # --------------------------- FEEDBACK UI -------------------------------- #
    @staticmethod
    def feedback_block_kit() -> List[Dict[str, Any]]:
        """Message-level feedback buttons (👍 / 👎)."""
        return [
            _divider(),
            _mk_section("Did you find our suggestion satisfactory?"),
            {
                "type": "actions",
                "elements": [
                    _mk_button("👍", action_id="vertex_positive", style="primary"),
                    _mk_button("👎", action_id="vertex_negative", style="danger"),
                ],
            },
        ]

    @staticmethod
    def thread_feedback_block_kit() -> List[Dict[str, Any]]:
        """Thread-level feedback buttons (👍 / 👎)."""
        return [
            _divider(),
            _mk_section("Did you find our suggestion satisfactory?"),
            {
                "type": "actions",
                "elements": [
                    _mk_button("👍", action_id="thread_positive", style="primary"),
                    _mk_button("👎", action_id="thread_negative", style="danger"),
                ],
            },
        ]

    # ------------------------ primary answer builder ------------------------ #
    def build_answer_blocks(self) -> Dict[str, Any]:
        """
        Build the main answer block set.
        - If llm_answer is missing → show 'no suggestions found'.
        - Insert link hints if we detect URLs.
        - Append message-level feedback buttons.
        """
        if not self.llm_answer:
            blocks = [_mk_section(f"Sorry, <@{self.user_id}> — no suggestions have been found.")]
            return {"blocks": blocks}

        answer = unescape(self.llm_answer or "")[:3000]  # keep slack-safe
        blocks: List[Dict[str, Any]] = [
            _mk_section(
                "Thank you for submitting a request with Cloud Tech. "
                "Based on your query, the following answer has been found:"
            ),
            _mk_section(answer),
        ]

        links = self.extract_links(answer)
        blocks.extend(self._link_hint_blocks(links))

        blocks.extend(self.feedback_block_kit())

        return {"blocks": blocks}

    # ------------------------ update/patch helpers -------------------------- #
    def feedback_update_block(self) -> List[Dict[str, Any]]:
        """
        Replace the top section text in an existing message with the
        escaped/trimmed LLM answer (used when editing a previous post).
        """
        if not self.block_body:
            return self.build_answer_blocks()["blocks"]

        updated = []
        for item in self.block_body:
            if item.get("type") == "section" and "text" in item:
                # cap each section to 3k as a guard
                item["text"]["text"] = unescape(item["text"]["text"])[:3000]
            updated.append(item)
        return updated

    def feedback_update_block_session(self) -> List[Dict[str, Any]]:
        """Same as feedback_update_block; kept for backward-compat with your older code."""
        return self.feedback_update_block()

    # ----------------------------- follow-ups -------------------------------- #
    @staticmethod
    def self_help_link_block() -> List[Dict[str, Any]]:
        """Small doc pointer used in your screens."""
        return [
            _mk_section(
                "Thank you for your feedback. Alternatively, you may also find the "
                "following self-help documentation useful:\n"
                "<https://cloudtech.apple.com/docs|CloudTech Docs>"
            )
        ]

    def followup_block_kit(self) -> List[Dict[str, Any]]:
        """Bot offers to help further via mention."""
        text = (
            "Not clear yet? I can guide you one step at a time — "
            f"just @mention <@{self.bot_id}> with your follow-up questions."
        )
        return [_mk_section(text)]

    def followup_delay_message(self) -> List[Dict[str, Any]]:
        """A gentle nudge after some delay."""
        text = (
            "Did you find the suggestion satisfactory? If not, you can ask me more "
            f"questions by sending me an @mention <@{self.bot_id}>."
        )
        return [_mk_section(text)]

    # ------------------------- thread answer builder ------------------------- #
    def thread_block_kit(self) -> List[Dict[str, Any]]:
        """A compact version suitable for replies in a thread."""
        if not self.llm_answer:
            return [_mk_section(f"Sorry, <@{self.user_id}> — no suggestions have been found.")]
        answer = unescape(self.llm_answer)[:3000]
        blocks: List[Dict[str, Any]] = [_mk_section(answer)]

        links = self.extract_links(answer)
        blocks.extend(self._link_hint_blocks(links))

        blocks.extend(self.thread_feedback_block_kit())
        return blocks

    # ---------------------- HelpCentral ticket blocks ----------------------- #
    @dataclass
    class HelpCentral:
        ticket_number: Optional[str] = None
        ticket_url: Optional[str] = None
        user_id: Optional[str] = None

        @staticmethod
        def open_ticket_cta() -> Dict[str, Any]:
            """CTA to open a ticket from the bot."""
            return {
                "blocks": [
                    _mk_section(
                        "Hello. If you are looking for assistance from CloudTech/CSE Support, "
                        "please click the button to open a ticket; someone will follow up with you."
                    ),
                    {
                        "type": "actions",
                        "elements": [
                            _mk_button("Open support request", action_id="vertex_raise_ticket"),
                        ],
                    },
                ]
            }

        def clicked_ticket_button(self) -> Dict[str, Any]:
            return {
                "blocks": [
                    _mk_section(f"<@{self.user_id}> clicked on *Open Support Request*"),
                ]
            }

        @staticmethod
        def ticket_creation_followup() -> Dict[str, Any]:
            """Rich text follow-up (Slack 'rich_text' block)."""
            return {
                "blocks": [
                    {
                        "type": "rich_text",
                        "elements": [
                            {
                                "type": "rich_text_section",
                                "elements": [
                                    {"type": "text", "text": "Creating your ticket… one moment please."}
                                ],
                            }
                        ],
                    }
                ]
            }

        def ticket_details(self) -> Dict[str, Any]:
            """Final message after ticket creation attempt."""
            if self.ticket_url:
                txt = (
                    f"The following HelpCentral ticket has been created on your behalf "
                    f"<{self.ticket_url}|{self.ticket_number}> — someone from our team will follow up.\n"
                    f"See SLA details: <https://cloudtech.apple.com/docs/sla|SLA link>"
                )
            else:
                txt = (
                    "There seems to be a problem while raising the ticket. "
                    "Please try again after some time or contact the development team."
                )
            return {"blocks": [_mk_section(txt)]}

        @staticmethod
        def hc_outage() -> Dict[str, Any]:
            """Outage banner (scheduled maintenance notice)."""
            return {
                "blocks": [
                    _mk_section(
                        "*Please be advised:* Due to a scheduled maintenance, "
                        "HelpCentral will be offline from Friday, 01/31/2025 8:00 PM PT "
                        "to Saturday, 02/01/2025."
                    )
                ]
            }
