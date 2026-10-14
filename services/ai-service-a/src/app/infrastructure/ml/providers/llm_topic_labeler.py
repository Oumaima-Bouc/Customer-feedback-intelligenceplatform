"""
LLMTopicLabeler — implements TopicLabelingPort.

Wraps the LLM API client for cluster labeling and merging.
Supports OpenAI-compatible, Ollama, and custom HTTP endpoints.
Configuration via LLMSettings.

If the LLM API is unreachable, is_available() returns False and the
orchestration layer falls back to the legacy topic classifier.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional
from urllib.parse import quote as _url_quote

import requests

from src.app.domain.ports import TopicLabelingPort
from src.app.infrastructure.config.settings import LLMSettings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# DOMAIN CONTEXT (embedded in every prompt)
# ═══════════════════════════════════════════════════════════════════════════════

DOMAIN_CONTEXT = """You are analyzing customer feedback from Algérie Télécom, the main telecommunications provider in Algeria.

KEY FACTS about this company and its customers:
- Services: fixed-line internet (ADSL, VDSL, Fiber/FTTH), 4G LTE mobile data, landline phone
- Main product brands: "Idoom Fibre", "Idoom ADSL", "Idoom 4G LTE"
- Customer portal/app: "Espace Client" (web) and "My Idoom" (mobile app)
- The company is deploying FTTH (fiber-to-the-home) across Algeria, but rollout is slow

COMMON CUSTOMER ISSUES (from most to least frequent):
1. Internet outages and disconnections (days/weeks without service)
2. Modem unavailability — fiber modems are chronically out of stock nationwide
3. Fiber deployment delays — customers wait months after their neighborhood is wired
4. Slow internet speeds — paying for 20/50/100 Mbps but getting 2-5 Mbps
5. App/portal issues — "Espace Client" and "My Idoom" frequently broken
6. Billing and pricing complaints — prices too high relative to service quality
7. Poor customer support — long wait times, unresolved tickets
8. Installation delays — technicians not showing up after signing up

LANGUAGE PATTERNS:
- Comments are in Arabic (MSA + Algerian Darija dialect), French, or Arabizi (Arabic written in Latin letters)
- Darija examples: "وينو المودام" (where's the modem), "مكانش" (there isn't any), "رانا نستناو" (we're waiting)
- Mixed French-Arabic is common: "الفيبر متوفرش في notre quartier" (fiber not available in our neighborhood)
- Aggressive/mocking tone is common and does NOT necessarily mean a different topic — it's an expression style

IMPORTANT FOR LABELING:
- Focus on the ISSUE/TOPIC being discussed, not the tone or language
- Two comments can discuss the same topic in very different words or languages
- "وين المودام" (where's the modem) and "modem indisponible depuis 3 mois" are the SAME topic
- Congratulatory messages ("مبروك", "félicitations", "bravo") often appear when AT announces new services"""


LABEL_PROMPT = """{domain_context}

TASK: You are given representative comments from ONE cluster of customer messages.
Produce a SHORT, SPECIFIC topic label (3-8 words, in English) that names the concrete issue or subject of this cluster.
A reader must understand the exact problem from the label alone.

WHAT A GOOD LABEL LOOKS LIKE (specific — name the actual issue):
- "Fiber modem out of stock"
- "Internet outage lasting days or weeks"
- "Fiber installation delay after signup"
- "Espace Client / My Idoom app not working"
- "Slow internet speed vs subscribed plan"
- "Subscription price and billing complaints"
- "4G coverage gaps in an area"
- "Fiber availability inquiry for a neighborhood"
- "Damaged or stolen network cable"
- "Congratulations on a new service launch"

FORBIDDEN LABELS (too generic — NEVER use these or any paraphrase of them):
"Service complaints", "Réclamation service", "Customer issues", "General feedback",
"Negative feedback", "Various problems", "Service quality", "Complaints", "Customer service".
These describe a tone or a broad category, not a topic. If you are tempted to use one, look harder
at the comments and name the SPECIFIC underlying issue instead.

RULES:
- Focus on the ISSUE/SUBJECT, never the emotion or tone (anger, sarcasm, politeness are NOT topics).
- Your label MUST be DISTINCT from labels already assigned to other clusters — find the precise distinguishing issue.
{existing_labels}
Representative comments from this cluster:
{comments}

Respond with ONLY the topic label in this exact format:
TOPIC: <your specific label>"""


MERGE_PROMPT = """{domain_context}

TASK: Below are topic clusters. Decide which clusters — if any — should be MERGED.

MERGING IS THE EXCEPTION, NOT THE RULE. Your default is to MERGE NOTHING.
Merge two clusters ONLY when they are about the EXACT SAME specific issue and differ solely in
language, wording, or tone.

MERGE — same specific issue, only the language/wording differs:
- "وين المودام" (where is the modem) + "modem indisponible depuis 3 mois" → both = fiber modem out of stock → MERGE.
- angry "ma connexion est lente!!" + polite "la vitesse est faible" → both = slow speed → MERGE.

DO NOT MERGE — the following are DIFFERENT topics, even though they are ALL complaints / all negative:
  internet outage  ≠  fiber installation delay  ≠  fiber modem out of stock  ≠  slow internet speed  ≠
  billing / pricing  ≠  4G coverage  ≠  Espace Client / My Idoom app issue  ≠  fiber availability inquiry  ≠
  damaged / stolen cable  ≠  poor customer support.
NEVER merge two clusters just because they are both negative, both complaints, both "service issues",
both "réclamations", or both broadly "about the internet". A shared emotion or a shared broad
category is NOT a reason to merge — only an identical specific issue is.

FORBIDDEN merged labels (producing one proves you over-merged — do NOT):
"Service complaints", "Réclamation service", "Customer issues", "General feedback", "Service quality",
"Various complaints", "Customer service". If the only common label you can find is this generic, the
clusters are DIFFERENT topics — leave them unchanged.

For any merge, "new_label" MUST be a SPECIFIC issue label (same style as the good examples above), never generic.
When in doubt, DO NOT merge.

Here are the clusters:

{clusters_description}

Respond in this EXACT JSON format (no extra text):
{{
  "merges": [
    {{"merge_into": <cluster_id to keep>, "absorb": [<cluster_ids to merge in>], "new_label": "<specific topic label>"}}
  ],
  "unchanged": [{all_cluster_ids}]
}}

If no merges are needed (this is the common case), respond:
{{"merges": [], "unchanged": [{all_cluster_ids}]}}"""


# ═══════════════════════════════════════════════════════════════════════════════
# LLM API CALL
# ═══════════════════════════════════════════════════════════════════════════════

def _call_llm(settings: LLMSettings, prompt: str, max_tokens: Optional[int] = None) -> str:
    """Send a prompt to the remote LLM API. Retries on failure."""
    _max_tokens = max_tokens or settings.max_tokens
    url = f"{settings.api_base_url.rstrip('/')}{settings.api_endpoint}"

    headers = {"Content-Type": "application/json"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"

    # Build request body based on API format
    body: dict | None = None
    if settings.api_format == "query_param":
        url = f"{url}?prompt={_url_quote(prompt)}"
        body = None
    elif settings.api_format == "openai":
        body = {
            "model": settings.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": _max_tokens,
            "temperature": settings.temperature,
        }
    elif settings.api_format == "ollama":
        body = {
            "model": settings.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": _max_tokens,
                "temperature": settings.temperature,
            },
        }
    else:
        body = {
            "model": settings.model_name,
            "prompt": prompt,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": _max_tokens,
            "temperature": settings.temperature,
        }

    last_error = None
    for attempt in range(1, settings.retry_attempts + 1):
        try:
            if body is not None:
                resp = requests.post(
                    url, json=body, headers=headers, timeout=settings.timeout_seconds,
                )
            else:
                resp = requests.post(
                    url, headers=headers, timeout=settings.timeout_seconds,
                )
            resp.raise_for_status()
            return _extract_response_text(settings.api_format, resp.json())
        except Exception as e:
            last_error = e
            if attempt < settings.retry_attempts:
                logger.warning(
                    "llm_api_retry",
                    extra={"attempt": attempt, "error": str(e)},
                )
                time.sleep(settings.retry_delay_seconds)

    raise ConnectionError(f"LLM API failed after {settings.retry_attempts} attempts: {last_error}")


def _extract_response_text(api_format: str, response: dict) -> str:
    """Extract generated text from API response based on format."""
    if api_format == "openai":
        return response["choices"][0]["message"]["content"].strip()
    elif api_format == "ollama":
        return response.get("response", "").strip()
    elif api_format == "query_param":
        for key in ("response", "text", "output", "generated_text", "content"):
            if key in response:
                val = response[key]
                return val.strip() if isinstance(val, str) else str(val)
        return str(response)
    else:
        for key in ["response", "text", "output", "generated_text", "content"]:
            if key in response:
                val = response[key]
                return val.strip() if isinstance(val, str) else str(val)
        if "choices" in response:
            choice = response["choices"][0]
            if "message" in choice:
                return choice["message"]["content"].strip()
            if "text" in choice:
                return choice["text"].strip()
        return str(response)


def _parse_topic_label(response: str) -> str:
    """Extract the topic label from LLM response."""
    for line in response.split("\n"):
        line = line.strip()
        if line.upper().startswith("TOPIC:"):
            return line[6:].strip().strip('"').strip("'")
    for line in response.split("\n"):
        line = line.strip()
        if line and len(line) < 100:
            return line.strip('"').strip("'")
    return response[:80].strip()


# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTER
# ═══════════════════════════════════════════════════════════════════════════════

class LLMTopicLabeler(TopicLabelingPort):
    """
    Production LLM-based topic labeler.
    Calls a local Gemma 4B API (or any OpenAI-compatible endpoint).
    """

    def __init__(self, settings: LLMSettings) -> None:
        self._settings = settings

    def is_available(self) -> bool:
        """
        Check whether the LLM backend (Ollama) is up AND the configured model
        is present in its library.

        Strategy:
          1. GET /api/tags  — Ollama-native: lists downloaded models.
             If the configured model name (or its base, e.g. 'gemma3') appears
             in the response, we return True immediately.
          2. Fallback: attempt a minimal 5-token completion.  This handles
             non-Ollama OpenAI-compatible backends that don't expose /api/tags.
        """
        if not self._settings.enabled:
            return False

        base_url = self._settings.api_base_url.rstrip("/")
        model_base = self._settings.model_name.split(":")[0]  # "gemma3:4b" → "gemma3"

        # ── Check 1: Ollama /api/tags (confirms model is downloaded) ─────────────
        try:
            resp = requests.get(f"{base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                if any(model_base in m.get("name", "") for m in models):
                    logger.debug(
                        "llm_available_via_tags",
                        extra={"model": self._settings.model_name, "found": len(models)},
                    )
                    return True
                # Ollama is up but model not yet pulled
                logger.warning(
                    "llm_model_not_in_library",
                    extra={"model": self._settings.model_name,
                           "available": [m.get("name") for m in models]},
                )
                return False
        except Exception:
            pass  # not Ollama, or network error — fall through to inference check

        # ── Check 2: generic /health probe + minimal completion ─────────────────
        try:
            _call_llm(self._settings, "Say OK", max_tokens=5)
            return True
        except Exception as exc:
            logger.warning("llm_availability_check_failed", extra={"error": str(exc)})
            return False

    def label_clusters(
        self,
        cluster_representatives: dict[int, list[str]],
    ) -> dict[int, str]:
        """Label each cluster via LLM API call, passing already-assigned labels for dedup."""
        labels: dict[int, str] = {}
        for cid, reps in sorted(cluster_representatives.items()):
            try:
                comments_text = "\n".join(f"  - {c}" for c in reps)

                # Build existing labels context so the LLM avoids duplicates
                if labels:
                    existing_lines = "\n".join(
                        f"  - Cluster {k}: \"{v}\"" for k, v in labels.items()
                    )
                    existing_labels_text = (
                        f"\nLabels already assigned to OTHER clusters (DO NOT duplicate these):\n"
                        f"{existing_lines}\n"
                    )
                else:
                    existing_labels_text = ""

                prompt = LABEL_PROMPT.format(
                    domain_context=DOMAIN_CONTEXT,
                    comments=comments_text,
                    existing_labels=existing_labels_text,
                )
                response = _call_llm(self._settings, prompt, max_tokens=50)
                labels[cid] = _parse_topic_label(response)
                logger.debug("cluster_labeled", extra={"cluster_id": cid, "label": labels[cid]})
            except Exception as e:
                logger.error("cluster_label_failed", extra={"cluster_id": cid, "error": str(e)})
                labels[cid] = f"Cluster {cid}"
        return labels

    def merge_clusters(
        self,
        clusters: list[dict],
    ) -> list[dict]:
        """Ask LLM to identify and merge clusters covering the same topic."""
        if not self._settings.merge_clusters or len(clusters) < 2:
            return clusters

        # Build description
        cluster_desc_parts = []
        all_ids = []
        for c in clusters:
            cid = c["cluster_id"]
            all_ids.append(str(cid))
            reps_text = "\n".join(f"      - {r}" for r in c.get("representatives", [])[:5])
            cluster_desc_parts.append(
                f"  CLUSTER {cid}: \"{c.get('topic_label', '')}\" ({c.get('size', 0)} comments)\n"
                f"    Representative comments:\n{reps_text}"
            )

        clusters_description = "\n\n".join(cluster_desc_parts)
        all_cluster_ids = ", ".join(all_ids)

        prompt = MERGE_PROMPT.format(
            domain_context=DOMAIN_CONTEXT,
            clusters_description=clusters_description,
            all_cluster_ids=all_cluster_ids,
        )

        try:
            response = _call_llm(self._settings, prompt, max_tokens=500)
            merge_plan = self._parse_merge_response(response, clusters)

            if not merge_plan["merges"]:
                return clusters

            return self._execute_merges(clusters, merge_plan)
        except Exception as e:
            logger.error("cluster_merge_failed", extra={"error": str(e)})
            return clusters

    @staticmethod
    def _parse_merge_response(response: str, clusters: list[dict]) -> dict:
        valid_ids = {c["cluster_id"] for c in clusters}
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                plan = json.loads(json_match.group())
            else:
                return {"merges": [], "unchanged": list(valid_ids)}
        except json.JSONDecodeError:
            return {"merges": [], "unchanged": list(valid_ids)}

        validated_merges = []
        for m in plan.get("merges", []):
            target = m.get("merge_into")
            absorb = m.get("absorb", [])
            new_label = m.get("new_label", "")
            if target in valid_ids and all(a in valid_ids for a in absorb):
                validated_merges.append({
                    "merge_into": target,
                    "absorb": absorb,
                    "new_label": new_label,
                })

        return {"merges": validated_merges, "unchanged": plan.get("unchanged", [])}

    @staticmethod
    def _execute_merges(clusters: list[dict], merge_plan: dict) -> list[dict]:
        cluster_map = {c["cluster_id"]: c for c in clusters}
        absorbed_ids: set = set()

        for merge in merge_plan["merges"]:
            target_id = merge["merge_into"]
            absorb_ids = merge["absorb"]
            new_label = merge["new_label"]

            target = cluster_map[target_id]
            for aid in absorb_ids:
                if aid in cluster_map and aid != target_id:
                    source = cluster_map[aid]
                    target.setdefault("comment_indices", []).extend(
                        source.get("comment_indices", [])
                    )
                    target["size"] = target.get("size", 0) + source.get("size", 0)
                    absorbed_ids.add(aid)

            if new_label:
                target["topic_label"] = new_label

        merged = [c for c in clusters if c["cluster_id"] not in absorbed_ids]
        merged.sort(key=lambda x: x.get("size", 0), reverse=True)
        for i, c in enumerate(merged):
            c["cluster_id"] = i

        logger.info(
            "clusters_merged",
            extra={"before": len(clusters), "after": len(merged)},
        )
        return merged
