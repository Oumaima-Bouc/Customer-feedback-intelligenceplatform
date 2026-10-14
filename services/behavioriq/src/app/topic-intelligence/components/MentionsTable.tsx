'use client';

import React, { useState, useMemo } from 'react';
import {
  ChevronDown,
  ChevronUp,
  ArrowUpDown,
  ArrowDown,
  ArrowUp,
  Square,
  CheckSquare,
  TrendingUp,
  TrendingDown,
  Minus,
  Lock,
  Send,
  Loader2,
  RotateCcw,
  CheckCircle2,
} from 'lucide-react';
import PlatformIcon from './PlatformIcon';

/* ─── Types ──────────────────────────────────────────────────── */

export interface Mention {
  id: string;
  platform: string;
  date: string;
  time: string;
  comment: string;
  fullComment: string;
  topic: string;
  sentiment: string;
  repliable: boolean;
  replyBlockedReason?: string;
  humanVerified: boolean;
  verifiedBy?: string;
}

const SENTIMENT_OPTIONS = ['Positive', 'Neutral', 'Negative'];

type SortField = 'date' | 'sentiment' | 'platform' | 'topic';
type SortDir = 'asc' | 'desc';

/* ─── Helpers ────────────────────────────────────────────────── */

const SENTIMENT_ORDER: Record<string, number> = {
  Positive: 0,
  Neutral: 1,
  Negative: 2,
};

function SentimentBadge({ sentiment }: { sentiment: string }) {
  const cfg: Record<string, { icon: React.ReactNode; color: string; bg: string }> = {
    Positive: { icon: <TrendingUp size={16} />, color: 'var(--positive)', bg: 'transparent' },
    Neutral: { icon: <Minus size={16} />, color: 'var(--warning)', bg: 'transparent' },
    Negative: { icon: <TrendingDown size={16} />, color: 'var(--negative)', bg: 'transparent' },
  };
  const s = cfg[sentiment] ?? cfg['Neutral'];
  return (
    <div
      className="flex items-center gap-2.5 px-3 py-2 rounded-lg"
      style={{ backgroundColor: s.bg }}
    >
      <span className="flex items-center justify-center" style={{ color: s.color }}>
        {s.icon}
      </span>
      <span className="text-sm font-bold whitespace-nowrap" style={{ color: s.color }}>
        {sentiment}
      </span>
    </div>
  );
}

// Brand-aligned palette (blue / green family) cycled for topic chips.
const TOPIC_COLORS = ['#0e5fa8', '#1c8a3c', '#1577ba', '#b9730a', '#0b4a82', '#2f9e44'];

function topicColor(topic: string): string {
  let h = 0;
  for (let i = 0; i < topic.length; i += 1) h = (h * 31 + topic.charCodeAt(i)) >>> 0;
  return TOPIC_COLORS[h % TOPIC_COLORS.length];
}

// Sentiment → brand colour: green positive, red negative, amber neutral.
function sentimentColor(sentiment: string): string {
  if (sentiment === 'Positive') return 'var(--positive)';
  if (sentiment === 'Negative') return 'var(--negative)';
  return 'var(--warning)';
}

function TopicBadge({ topic }: { topic: string }) {
  const color = topicColor(topic);
  const meta = { color, bg: 'transparent', dot: color };
  return (
    <div
      className="inline-flex items-center gap-2 px-3 py-2 rounded-lg whitespace-nowrap"
      style={{ backgroundColor: meta.bg }}
    >
      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: meta.dot }} />
      <span className="text-sm font-bold" style={{ color: meta.color }}>
        {topic}
      </span>
    </div>
  );
}

function SortIcon({
  active,
  sortDir,
}: {
  field: string;
  active: boolean;
  sortDir?: 'asc' | 'desc';
}) {
  if (active && sortDir) {
    const Icon = sortDir === 'asc' ? ArrowUp : ArrowDown;
    return (
      <Icon
        size={12}
        className="inline-block ml-1"
        style={{ color: 'var(--primary)', strokeWidth: 3 }}
      />
    );
  }
  return (
    <ArrowUpDown
      size={12}
      className="inline-block ml-1"
      style={{ color: 'var(--muted-foreground)' }}
    />
  );
}

const ROWS_PER_PAGE = 8;

/* ─── Main component ─────────────────────────────────────────── */

interface MentionsTableProps {
  mentions: Mention[];
  /** Queue one reply under each explicitly-selected comment. Returns true on success. */
  onQueueReplies?: (ids: string[], text: string) => Promise<boolean>;
  /** Queue one reply under every comment matching the active topic/sentiment filter (R3). */
  onQueueAllMatching?: (text: string) => Promise<boolean>;
  /** Whether server-side "select all matching" is available for the current filter. */
  canSelectAllMatching?: boolean;
  /** Known topic labels (registry) — currently unused for autocomplete (free text), reserved. */
  availableTopics?: string[];
  /** Correct one comment's topic/sentiment. Returns true on success. */
  onFeedbackSingle?: (id: string, topic?: string, sentiment?: string) => Promise<boolean>;
  /** Correct many comments with the same label. Returns true on success. */
  onFeedbackBulk?: (ids: string[], topic?: string, sentiment?: string) => Promise<boolean>;
}

const MAX_REPLY_LEN = 1000;

export default function MentionsTable({
  mentions,
  onQueueReplies,
  onQueueAllMatching,
  canSelectAllMatching = false,
  onFeedbackSingle,
  onFeedbackBulk,
}: MentionsTableProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [sortField, setSortField] = useState<SortField>('date');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [currentPage, setCurrentPage] = useState(1);
  const [replyText, setReplyText] = useState('');
  const [submitting, setSubmitting] = useState(false);

  /* ── Selection (only repliable comments are selectable — R8/R9/R10) ── */
  const repliableIds = useMemo(
    () => mentions.filter((m) => m.repliable).map((m) => m.id),
    [mentions]
  );

  const toggleSelect = (id: string, repliable: boolean) => {
    if (!repliable) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () =>
    setSelected(
      selected.size === repliableIds.length && repliableIds.length > 0
        ? new Set()
        : new Set(repliableIds)
    );

  /* ── Group Reply submit ── */
  const composerOpen = selected.size > 0 || canSelectAllMatching;

  const queueSelected = async () => {
    if (!onQueueReplies || !replyText.trim() || selected.size === 0) return;
    setSubmitting(true);
    const ok = await onQueueReplies([...selected], replyText.trim());
    setSubmitting(false);
    if (ok) {
      setSelected(new Set());
      setReplyText('');
    }
  };

  const queueAllMatching = async () => {
    if (!onQueueAllMatching || !replyText.trim()) return;
    setSubmitting(true);
    const ok = await onQueueAllMatching(replyText.trim());
    setSubmitting(false);
    if (ok) {
      setSelected(new Set());
      setReplyText('');
    }
  };

  /* ── Label Feedback: inline edits (R1–R4, R11) ── */
  const [pending, setPending] = useState<Record<string, { topic?: string; sentiment?: string }>>({});
  const [savingFeedback, setSavingFeedback] = useState(false);

  const byId = useMemo(() => {
    const m: Record<string, Mention> = {};
    for (const x of mentions) m[x.id] = x;
    return m;
  }, [mentions]);

  const effTopic = (row: Mention) => pending[row.id]?.topic ?? row.topic;
  const effSentiment = (row: Mention) => pending[row.id]?.sentiment ?? row.sentiment;

  // Targets for an inline edit: the selected (non-verified) set when editing a
  // selected row with a multi-selection (bulk mirror, R11), else just this row.
  const editTargets = (row: Mention): string[] => {
    if (selected.has(row.id) && selected.size > 1) {
      return [...selected].filter((id) => byId[id] && !byId[id].humanVerified);
    }
    return [row.id];
  };

  const setField = (row: Mention, field: 'topic' | 'sentiment', value: string) => {
    const ids = editTargets(row);
    setPending((prev) => {
      const next = { ...prev };
      for (const id of ids) next[id] = { ...next[id], [field]: value };
      return next;
    });
  };

  // A pending entry is a real change only when it differs from the row's current label.
  const changeFor = (id: string): { topic?: string; sentiment?: string } | null => {
    const p = pending[id];
    const orig = byId[id];
    if (!p || !orig) return null;
    const out: { topic?: string; sentiment?: string } = {};
    if (p.topic !== undefined && p.topic.trim() !== '' && p.topic !== orig.topic) out.topic = p.topic.trim();
    if (p.sentiment !== undefined && p.sentiment !== orig.sentiment) out.sentiment = p.sentiment.toLowerCase();
    return out.topic || out.sentiment ? out : null;
  };

  const dirtyIds = useMemo(
    () => Object.keys(pending).filter((id) => changeFor(id) !== null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pending, byId]
  );

  const resetFeedback = () => setPending({});

  const saveFeedback = async () => {
    const changes = dirtyIds.map((id) => ({ id, ...changeFor(id)! }));
    if (changes.length === 0) return;
    setSavingFeedback(true);
    let ok = false;
    if (changes.length === 1 && onFeedbackSingle) {
      ok = await onFeedbackSingle(changes[0].id, changes[0].topic, changes[0].sentiment);
    } else {
      const uniform = changes.every(
        (c) => c.topic === changes[0].topic && c.sentiment === changes[0].sentiment
      );
      if (uniform && onFeedbackBulk) {
        ok = await onFeedbackBulk(changes.map((c) => c.id), changes[0].topic, changes[0].sentiment);
      } else if (onFeedbackSingle) {
        const results = await Promise.all(
          changes.map((c) => onFeedbackSingle(c.id, c.topic, c.sentiment))
        );
        ok = results.some(Boolean);
      }
    }
    setSavingFeedback(false);
    if (ok) {
      setPending({});
      setSelected(new Set());
    }
  };

  /* ── Sorting ── */
  const handleSort = (field: SortField) => {
    if (sortField === field) setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    else {
      setSortField(field);
      setSortDir('desc');
    }
    setCurrentPage(1);
  };

  const sorted = useMemo(() => {
    return [...mentions].sort((a, b) => {
      let diff = 0;
      if (sortField === 'sentiment') {
        diff = SENTIMENT_ORDER[a.sentiment] - SENTIMENT_ORDER[b.sentiment];
      } else if (sortField === 'platform') {
        diff = a.platform.localeCompare(b.platform);
      } else if (sortField === 'topic') {
        diff = a.topic.localeCompare(b.topic);
      } else {
        /* date — use id as proxy (m-001 … m-020) */
        diff = a.id.localeCompare(b.id);
      }
      return sortDir === 'asc' ? diff : -diff;
    });
  }, [mentions, sortField, sortDir]);

  /* ── Pagination ── */
  const totalPages = Math.max(1, Math.ceil(sorted.length / ROWS_PER_PAGE));
  const safeCurrentPage = Math.min(currentPage, totalPages);
  const paginated = sorted.slice(
    (safeCurrentPage - 1) * ROWS_PER_PAGE,
    safeCurrentPage * ROWS_PER_PAGE
  );

  /* ── Empty state ── */
  if (mentions.length === 0) {
    return (
      <div className="panel py-20 text-center">
        <p className="text-sm font-bold text-foreground">No mentions found</p>
        <p className="text-xs text-muted-foreground mt-1">
          Try adjusting your filters to see results
        </p>
      </div>
    );
  }

  return (
    <div className="panel overflow-hidden">
      {/* ── Group Reply composer ── */}
      {composerOpen && (
        <div
          className="flex flex-col gap-3 px-5 py-4 border-b border-border slide-up"
          style={{ backgroundColor: 'rgba(14,95,168,0.06)' }}
        >
          <div className="flex items-center gap-3">
            <span className="text-sm font-semibold" style={{ color: 'var(--primary)' }}>
              {selected.size > 0
                ? `${selected.size} comment${selected.size > 1 ? 's' : ''} selected`
                : 'Reply to all matching comments'}
            </span>
            {selected.size > 0 && (
              <button
                onClick={() => setSelected(new Set())}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                Clear
              </button>
            )}
          </div>

          <textarea
            value={replyText}
            onChange={(e) => setReplyText(e.target.value.slice(0, MAX_REPLY_LEN))}
            rows={2}
            placeholder="Write one reply to publish under every selected comment…"
            disabled={submitting}
            className="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none transition-colors focus:border-primary disabled:opacity-60"
          />

          <div className="flex flex-wrap items-center gap-2">
            {selected.size > 0 && (
              <button
                onClick={queueSelected}
                disabled={submitting || !replyText.trim()}
                className="btn-primary inline-flex items-center gap-1.5 text-xs py-1.5 px-3 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {submitting ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                Queue reply to {selected.size} selected
              </button>
            )}
            {canSelectAllMatching && onQueueAllMatching && (
              <button
                onClick={queueAllMatching}
                disabled={submitting || !replyText.trim()}
                className="btn-secondary inline-flex items-center gap-1.5 text-xs py-1.5 px-3 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {submitting ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                Reply to all matching
              </button>
            )}
            <span className="ml-auto text-2xs text-muted-foreground tabular-nums">
              {replyText.length}/{MAX_REPLY_LEN} · replies send within the next 24h
            </span>
          </div>
        </div>
      )}

      {/* ── Table ── */}
      <div className="overflow-x-auto scrollbar-thin">
        <table className="w-full min-w-[880px]">
          <thead>
            <tr className="border-b border-border bg-muted/50">
              {/* Checkbox */}
              <th className="w-10 px-4 py-3 text-left">
                <button
                  onClick={toggleAll}
                  disabled={repliableIds.length === 0}
                  title={repliableIds.length === 0 ? 'No repliable comments on this page' : 'Select all repliable'}
                  className="text-muted-foreground hover:text-foreground transition-colors flex items-center disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {selected.size === repliableIds.length && repliableIds.length > 0 ? (
                    <CheckSquare size={15} style={{ color: 'var(--primary)' }} />
                  ) : (
                    <Square size={15} />
                  )}
                </button>
              </th>
              {/* Platform */}
              <th
                className="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-muted-foreground cursor-pointer hover:text-foreground transition-colors whitespace-nowrap"
                onClick={() => handleSort('platform')}
              >
                Platform{' '}
                <SortIcon field="platform" active={sortField === 'platform'} sortDir={sortDir} />
              </th>
              {/* Date */}
              <th
                className="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-muted-foreground cursor-pointer hover:text-foreground transition-colors whitespace-nowrap"
                onClick={() => handleSort('date')}
              >
                Time <SortIcon field="date" active={sortField === 'date'} sortDir={sortDir} />
              </th>
              {/* Comment */}
              <th className="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-muted-foreground w-full">
                Comment
              </th>
              {/* Topic */}
              <th
                className="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-muted-foreground cursor-pointer hover:text-foreground transition-colors whitespace-nowrap"
                onClick={() => handleSort('topic')}
              >
                Topic <SortIcon field="topic" active={sortField === 'topic'} sortDir={sortDir} />
              </th>
              {/* Sentiment */}
              <th
                className="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-muted-foreground cursor-pointer hover:text-foreground transition-colors whitespace-nowrap"
                onClick={() => handleSort('sentiment')}
              >
                Sentiment Indicator{' '}
                <SortIcon field="sentiment" active={sortField === 'sentiment'} sortDir={sortDir} />
              </th>
            </tr>
          </thead>

          <tbody>
            {paginated.map((row, idx) => {
              const isSelected = selected.has(row.id);
              const isExpanded = expandedId === row.id;

              return (
                <React.Fragment key={row.id}>
                  {/* ── Main row ── */}
                  <tr
                    className={`border-b border-border transition-colors duration-100 group ${
                      isSelected ? 'bg-secondary' : idx % 2 === 0 ? 'bg-card' : 'bg-muted/40'
                    } hover:bg-muted/70`}
                  >
                    {/* Checkbox — disabled + lock for non-repliable comments (R8/R9/R10) */}
                    <td className="px-4 py-3.5 text-left align-middle w-10">
                      {row.repliable ? (
                        <button
                          onClick={() => toggleSelect(row.id, true)}
                          className="text-muted-foreground hover:text-foreground flex items-center"
                          title="Select for reply"
                        >
                          {isSelected ? (
                            <CheckSquare size={15} style={{ color: 'var(--primary)' }} />
                          ) : (
                            <Square size={15} />
                          )}
                        </button>
                      ) : (
                        <span
                          className="flex items-center text-muted-foreground/50 cursor-not-allowed"
                          title={row.replyBlockedReason || 'Not available for reply'}
                        >
                          <Lock size={14} />
                        </span>
                      )}
                    </td>

                    {/* Platform */}
                    <td className="px-4 py-3.5 text-left">
                      <div className="flex items-center gap-2.5">
                        <PlatformIcon platform={row.platform.toLowerCase()} size={30} />
                        <span className="text-sm font-semibold text-foreground whitespace-nowrap">
                          {row.platform === 'Twitter' ? 'X' : row.platform}
                        </span>
                      </div>
                    </td>

                    {/* Date & Time */}
                    <td className="px-4 py-3.5 text-left whitespace-nowrap">
                      <p className="text-sm font-semibold text-foreground">{row.date}</p>
                      <p className="text-xs font-medium text-slate-600 mt-0.5">{row.time}</p>
                    </td>

                    {/* Comment */}
                    <td className="px-4 py-4 text-left w-full max-w-[400px]">
                      <p className="text-sm font-medium text-foreground leading-relaxed line-clamp-2">
                        &ldquo;{row.comment}&rdquo;
                      </p>
                      {row.fullComment !== row.comment && (
                        <button
                          onClick={() => setExpandedId(isExpanded ? null : row.id)}
                          className="mt-1 text-sm font-bold transition-colors hover:underline"
                          style={{ color: 'var(--primary)' }}
                        >
                          {isExpanded ? 'Show less' : 'Read more...'}
                        </button>
                      )}
                    </td>

                    {/* Topic — inline-editable unless already corrected (locked) */}
                    <td className="px-4 py-3.5 text-left whitespace-nowrap">
                      {row.humanVerified ? (
                        <span
                          className="inline-flex items-center gap-1.5"
                          title={row.verifiedBy ? `Corrected by ${row.verifiedBy}` : 'Corrected'}
                        >
                          <TopicBadge topic={row.topic} />
                          <Lock size={12} className="text-muted-foreground/70" />
                        </span>
                      ) : (
                        <div
                          className="inline-flex items-center gap-2 rounded-lg px-1.5 transition-colors"
                          style={{ backgroundColor: changeFor(row.id)?.topic ? 'rgba(14,95,168,0.10)' : 'transparent' }}
                        >
                          <span
                            className="w-2 h-2 rounded-full flex-shrink-0"
                            style={{ backgroundColor: topicColor(effTopic(row)) }}
                          />
                          <input
                            value={effTopic(row)}
                            onChange={(e) => setField(row, 'topic', e.target.value)}
                            maxLength={80}
                            aria-label="Topic"
                            className="w-40 bg-transparent py-1.5 text-sm font-bold outline-none placeholder:text-muted-foreground"
                            style={{ color: topicColor(effTopic(row)) }}
                          />
                        </div>
                      )}
                    </td>

                    {/* Sentiment — inline dropdown unless locked */}
                    <td className="px-4 py-3.5 text-left whitespace-nowrap w-[1px]">
                      {row.humanVerified ? (
                        <SentimentBadge sentiment={row.sentiment} />
                      ) : (
                        <select
                          value={effSentiment(row)}
                          onChange={(e) => setField(row, 'sentiment', e.target.value)}
                          aria-label="Sentiment"
                          className="rounded-lg bg-transparent px-2 py-1.5 text-sm font-bold outline-none transition-colors cursor-pointer hover:bg-muted/50"
                          style={{
                            color: sentimentColor(effSentiment(row)),
                            backgroundColor: changeFor(row.id)?.sentiment ? 'rgba(14,95,168,0.10)' : undefined,
                          }}
                        >
                          {SENTIMENT_OPTIONS.map((s) => (
                            <option key={s} value={s} style={{ color: 'var(--foreground)' }}>
                              {s}
                            </option>
                          ))}
                        </select>
                      )}
                    </td>
                  </tr>

                  {/* ── Expanded row ── */}
                  {isExpanded && (
                    <tr className="border-b border-border">
                      <td
                        colSpan={6}
                        className="px-16 py-5"
                        style={{ backgroundColor: 'rgba(14,95,168,0.025)' }}
                      >
                        <div className="space-y-3">
                          <p className="text-base font-medium text-foreground leading-relaxed">
                            &ldquo;{row.fullComment}&rdquo;
                          </p>
                          <div className="flex flex-wrap gap-5 text-xs text-muted-foreground pt-1">
                            <span>
                              Platform: <strong className="text-foreground">{row.platform}</strong>
                            </span>
                            <span>
                              Topic: <strong className="text-foreground">{row.topic}</strong>
                            </span>
                            <span>
                              Date:{' '}
                              <strong className="text-foreground">
                                {row.date} · {row.time}
                              </strong>
                            </span>
                            <span>
                              Sentiment:{' '}
                              <strong
                                style={{
                                  color:
                                    row.sentiment === 'Positive'
                                      ? 'var(--positive)'
                                      : row.sentiment === 'Negative'
                                        ? 'var(--negative)'
                                        : 'var(--warning)',
                                }}
                              >
                                {row.sentiment}
                              </strong>
                            </span>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* ── Label Feedback save bar (appears once any label is edited — R4) ── */}
      {dirtyIds.length > 0 && (
        <div
          className="flex flex-wrap items-center gap-3 px-5 py-3 border-t border-border slide-up"
          style={{ backgroundColor: 'rgba(28,138,60,0.07)' }}
        >
          <span className="text-sm font-semibold" style={{ color: 'var(--positive)' }}>
            {dirtyIds.length} correction{dirtyIds.length > 1 ? 's' : ''} pending
          </span>
          <span className="text-2xs text-muted-foreground">Corrections are final once saved.</span>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={resetFeedback}
              disabled={savingFeedback}
              className="btn-secondary inline-flex items-center gap-1.5 text-xs py-1.5 px-3 disabled:opacity-60"
            >
              <RotateCcw size={14} />
              Reset
            </button>
            <button
              onClick={saveFeedback}
              disabled={savingFeedback}
              className="btn-primary inline-flex items-center gap-1.5 text-xs py-1.5 px-3 disabled:opacity-60"
            >
              {savingFeedback ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
              Save {dirtyIds.length > 1 ? `${dirtyIds.length} corrections` : 'correction'}
            </button>
          </div>
        </div>
      )}

      {/* ── Pagination ── */}
      <div className="flex flex-col gap-3 px-5 py-3.5 border-t border-border bg-muted/20 sm:flex-row sm:items-center sm:justify-between">
        <span className="text-xs text-muted-foreground tabular-nums">
          Showing {Math.min((safeCurrentPage - 1) * ROWS_PER_PAGE + 1, mentions.length)}–
          {Math.min(safeCurrentPage * ROWS_PER_PAGE, mentions.length)} of {mentions.length} mentions
        </span>

        <div className="flex items-center gap-1">
          {/* Prev */}
          <button
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
            disabled={safeCurrentPage === 1}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-sm border border-border hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed transition-all"
          >
            <ChevronDown size={14} className="rotate-90" />
          </button>

          {/* Page numbers */}
          {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
            <button
              key={page}
              onClick={() => setCurrentPage(page)}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-semibold border transition-all"
              style={{
                borderColor: safeCurrentPage === page ? 'var(--primary)' : 'var(--border)',
                backgroundColor: safeCurrentPage === page ? 'rgba(14,95,168,0.08)' : 'transparent',
                color: safeCurrentPage === page ? 'var(--primary)' : 'var(--foreground)',
              }}
            >
              {page}
            </button>
          ))}

          {/* Next */}
          <button
            onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
            disabled={safeCurrentPage === totalPages}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-sm border border-border hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed transition-all"
          >
            <ChevronUp size={14} className="rotate-90" />
          </button>
        </div>
      </div>
    </div>
  );
}
