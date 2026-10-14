from modules.topics.topic_model import list_topic_names, fetch_topic_comments
from modules.dashboard.dashboard_service import get_topic_cards
def get_topics_list(run_date: str = "") -> dict: return {"topics": list_topic_names(run_date)}
def get_all_topics() -> dict: return get_topic_cards()
def get_topic_comments(topic_name: str, cursor: str = "", limit: int = 10) -> dict: return fetch_topic_comments(topic_name, cursor, limit)
