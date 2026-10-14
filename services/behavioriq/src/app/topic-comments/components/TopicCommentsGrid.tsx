'use client';

import React, { useEffect, useState } from 'react';
import TopicCommentCard, { TopicCommentData } from './TopicCommentCard';
import { getTopics, getTopicComments } from '@/lib/api';

function toStatus(pos: number, neg: number): 'healthy' | 'warning' | 'critical' {
  if (neg > 40) return 'critical';
  if (neg > 20 || pos < 40) return 'warning';
  return 'healthy';
}

export default function TopicCommentsGrid() {
  const [topics, setTopics] = useState<TopicCommentData[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getTopics()
      .then(async (res: any) => {
        const data = Array.isArray(res) ? res : res.topics || [];
        const topicsWithComments = await Promise.all(
          data.slice(0, 12).map(async (t: any, i: number) => {
            let comments: any[] = [];
            try {
              const cdata = await getTopicComments(t.topic, { limit: 50 });
              comments = (cdata.comments || []).map((c: any, ci: number) => ({
                id: `c${ci}`,
                author: 'User',
                initials: 'U',
                avatarColor: '#9CA3AF',
                timeAgo: 'recently',
                text: c.text_content || '',
                commentSentiment: (c.sentiment || 'neutral').toLowerCase(),
              }));
            } catch {
              // Keep the topic card visible even when recent comments fail to load.
            }
            const sentiment = {
              positive: Math.round(t.sentiment?.positive_pct || 0),
              neutral: Math.round(t.sentiment?.neutral_pct || 0),
              negative: Math.round(t.sentiment?.negative_pct || 0),
            };
            const totalSourceCount = (t.sources || []).reduce(
              (sum: number, s: any) => sum + (s.count || 0),
              0
            );
            const sources = (t.sources || []).map((s: any) => ({
              name:
                s.source === 'facebook'
                  ? 'FB'
                  : s.source === 'instagram'
                    ? 'IG'
                    : s.source === 'twitter'
                      ? 'TW'
                      : 'TT',
              pct: totalSourceCount > 0 ? Math.round((s.count / totalSourceCount) * 100) : 0,
              color:
                s.source === 'facebook'
                  ? '#1877F2'
                  : s.source === 'instagram'
                    ? '#E1306C'
                    : s.source === 'twitter'
                      ? '#1D9BF0'
                      : '#111827',
            }));
            return {
              id: `topic-${i}`,
              name: t.topic,
              category: 'General',
              sentiment,
              platforms: sources,
              trend: 0,
              aiConfidence: 90,
              mentions: t.comment_count || 0,
              status: toStatus(sentiment.positive, sentiment.negative),
              comments,
            };
          })
        );
        setTopics(topicsWithComments);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
          <div key={i} className="h-[360px] panel skeleton" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 items-start">
      {topics.map((topic) => (
        <TopicCommentCard key={topic.id} topic={topic} />
      ))}
    </div>
  );
}
