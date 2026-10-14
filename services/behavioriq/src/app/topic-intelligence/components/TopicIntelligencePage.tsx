'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  getComments,
  getTopicsList,
  submitReplies,
  submitFeedback,
  submitFeedbackBulk,
  ReplyAck,
} from '@/lib/api';
import MentionsKPIRow from './MentionsKPIRow';
import MentionsFilterBar from './MentionsFilterBar';
import MentionsTable, { Mention } from './MentionsTable';

const PLATFORM_LABELS: Record<string, string> = {
  facebook: 'Facebook',
  instagram: 'Instagram',
  twitter: 'Twitter',
  tiktok: 'TikTok',
};

function capFirst(s: string) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : '';
}

export default function TopicIntelligencePage() {
  const [mentions, setMentions] = useState<Mention[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [availableTopics, setAvailableTopics] = useState<string[]>([]);
  const [availableSources, setAvailableSources] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  // Aggregates over the CURRENT filter (computed server-side) — drive the KPI cards.
  const [agg, setAgg] = useState<{
    total: number;
    sentiment: { positive: number; neutral: number; negative: number };
    sources: { source: string; count: number }[];
  }>({ total: 0, sentiment: { positive: 0, neutral: 0, negative: 0 }, sources: [] });

  /* ── Filter state ── */
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);
  const [topicFilter, setTopicFilter] = useState<string | null>(null);
  const [sentimentFilter, setSentimentFilter] = useState<string | null>(null);

  const mapComment = (c: any, i: number): Mention => {
    const d = new Date(c.scraped_at || c.created_at || Date.now());
    return {
      id: c.comment_id || `c-${i}`,
      platform: PLATFORM_LABELS[c.source] || capFirst(c.source),
      date: d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }),
      time: d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }),
      comment: (c.text_content || '').slice(0, 120) + ((c.text_content || '').length > 120 ? '...' : ''),
      fullComment: c.text_content || '',
      topic: c.topic || 'General',
      sentiment: capFirst(c.sentiment),
      repliable: !!c.repliable,
      replyBlockedReason: c.reply_blocked_reason || undefined,
      humanVerified: !!c.human_verified,
      verifiedBy: c.verified_by || undefined,
    };
  };

  // Server-side filtered fetch — the table AND the KPI aggregates reflect the active
  // filter (or the whole run when no filter). `silent` skips the skeleton on refresh.
  const load = useCallback((silent = false) => {
    if (!silent) setLoading(true);
    return getComments({
      limit: 100,
      source: sourceFilter ? sourceFilter.toLowerCase() : undefined,
      sentiment: sentimentFilter ? sentimentFilter.toLowerCase() : undefined,
      topic: topicFilter || undefined,
    })
      .then((d: any) => {
        setMentions((d.comments || []).map(mapComment));
        setAgg({
          total: d.total_comments ?? 0,
          sentiment: d.sentiment || { positive: 0, neutral: 0, negative: 0 },
          sources: d.sources || [],
        });
        setTotalCount(d.total_comments ?? 0);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [sourceFilter, sentimentFilter, topicFilter]);

  useEffect(() => {
    load();
  }, [load]);

  // Filter OPTIONS (run-wide, independent of the active filter): topics present in
  // this run's comments + the platforms present in this run.
  useEffect(() => {
    getTopicsList()
      .then((t: any) => setAvailableTopics(Array.isArray(t) ? t : []))
      .catch(() => {});
    getComments({ limit: 1 })
      .then((d: any) =>
        setAvailableSources(
          (d.sources || []).map((s: any) => PLATFORM_LABELS[s.source] || capFirst(s.source))
        )
      )
      .catch(() => {});
  }, []);

  /* ── Group Reply submit handlers (R1/R3) ── */
  function notifyAck(ack: ReplyAck) {
    const skipped = ack.skipped.not_repliable + ack.skipped.already_queued;
    toast.success(ack.message, {
      description: `Queued ${ack.accepted}${skipped ? ` · skipped ${skipped}` : ''}.`,
    });
  }

  const handleQueueReplies = async (ids: string[], text: string): Promise<boolean> => {
    try {
      notifyAck(await submitReplies({ reply_text: text, comment_ids: ids }));
      return true;
    } catch (e: any) {
      toast.error(e?.message || 'Could not queue replies.');
      return false;
    }
  };

  // Server-side "select all matching" (R3) — only topic/sentiment are matched
  // server-side, so it is offered only when no source filter narrows the view.
  const canSelectAllMatching = (!!topicFilter || !!sentimentFilter) && !sourceFilter;

  const handleQueueAllMatching = async (text: string): Promise<boolean> => {
    try {
      notifyAck(
        await submitReplies({
          reply_text: text,
          select_all_matching: true,
          filter: {
            topic: topicFilter || undefined,
            sentiment: sentimentFilter ? sentimentFilter.toLowerCase() : undefined,
          },
        })
      );
      return true;
    } catch (e: any) {
      toast.error(e?.message || 'Could not queue replies.');
      return false;
    }
  };

  /* ── Label Feedback handlers (R1–R3, R11) ── */
  const handleFeedbackSingle = async (
    id: string,
    topic?: string,
    sentiment?: string
  ): Promise<boolean> => {
    try {
      await submitFeedback({ comment_id: id, new_topic: topic, new_sentiment: sentiment });
      toast.success('Correction saved.');
      load(true);
      return true;
    } catch (e: any) {
      toast.error(e?.message || 'Could not save the correction.');
      return false;
    }
  };

  const handleFeedbackBulk = async (
    ids: string[],
    topic?: string,
    sentiment?: string
  ): Promise<boolean> => {
    try {
      const r = await submitFeedbackBulk({ comment_ids: ids, new_topic: topic, new_sentiment: sentiment });
      const skipped = r.skipped?.length || 0;
      toast.success(
        `Saved ${r.applied.length} correction${r.applied.length === 1 ? '' : 's'}` +
          (skipped ? ` · ${skipped} skipped (already corrected)` : '') +
          '.'
      );
      load(true);
      return true;
    } catch (e: any) {
      toast.error(e?.message || 'Could not save the corrections.');
      return false;
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-24 panel skeleton" />
        <div className="h-16 panel skeleton" />
        <div className="h-96 panel skeleton" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ── KPI row (run-wide aggregates) ── */}
      <MentionsKPIRow total={agg.total} sentiment={agg.sentiment} sources={agg.sources} />

      {/* ── Filter bar ── */}
      <MentionsFilterBar
        sourceFilter={sourceFilter}
        topicFilter={topicFilter}
        sentimentFilter={sentimentFilter}
        availableTopics={availableTopics}
        availableSources={availableSources}
        onSourceChange={setSourceFilter}
        onTopicChange={setTopicFilter}
        onSentimentChange={setSentimentFilter}
        totalCount={totalCount}
        filteredCount={mentions.length}
      />

      {/* ── Mentions table ── */}
      <MentionsTable
        mentions={mentions}
        onQueueReplies={handleQueueReplies}
        onQueueAllMatching={handleQueueAllMatching}
        canSelectAllMatching={canSelectAllMatching}
        availableTopics={availableTopics}
        onFeedbackSingle={handleFeedbackSingle}
        onFeedbackBulk={handleFeedbackBulk}
      />
    </div>
  );
}
