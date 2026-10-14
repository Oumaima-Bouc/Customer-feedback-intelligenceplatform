from modules.comments.comment_model import fetch_paginated, count_filtered
def list_comments(cursor: str, limit: int, source: str, sentiment: str, topic: str): return fetch_paginated(cursor, limit, source, sentiment, topic)
def count_comments(source: str, sentiment: str, topic: str) -> dict: return {"count": count_filtered(source, sentiment, topic)}
