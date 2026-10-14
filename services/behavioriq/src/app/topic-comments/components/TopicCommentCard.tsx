'use client';

import React, { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

/* ─── Sentiment colours — Algérie Télécom brand tokens (hex for SVG fill) ─── */
const POS_COLOR = '#1c8a3c';
const NEU_COLOR = '#b9730a';
const NEG_COLOR = '#cf2b20';

/* ─── Donut chart ────────────────────────────────────────────── */
function polar(cx: number, cy: number, r: number, deg: number) {
  const rad = (deg * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function arcPath(
  cx: number,
  cy: number,
  outerR: number,
  innerR: number,
  startDeg: number,
  endDeg: number
): string {
  const os = polar(cx, cy, outerR, startDeg);
  const oe = polar(cx, cy, outerR, endDeg);
  const ie = polar(cx, cy, innerR, endDeg);
  const is_ = polar(cx, cy, innerR, startDeg);
  const large = endDeg - startDeg > 180 ? 1 : 0;

  return [
    `M ${os.x.toFixed(2)} ${os.y.toFixed(2)}`,
    `A ${outerR} ${outerR} 0 ${large} 1 ${oe.x.toFixed(2)} ${oe.y.toFixed(2)}`,
    `L ${ie.x.toFixed(2)} ${ie.y.toFixed(2)}`,
    `A ${innerR} ${innerR} 0 ${large} 0 ${is_.x.toFixed(2)} ${is_.y.toFixed(2)}`,
    'Z',
  ].join(' ');
}

interface DonutProps {
  positive: number;
  neutral: number;
  negative: number;
  trend: number;
}

function DonutChart({ positive, neutral, negative, trend }: DonutProps) {
  const SIZE = 124;
  const cx = SIZE / 2;
  const cy = SIZE / 2;
  const outerR = 56;
  const innerR = 37;
  const GAP_DEG = 2.5;

  const segments = [
    { value: positive, color: POS_COLOR },
    { value: neutral, color: NEU_COLOR },
    { value: negative, color: NEG_COLOR },
  ];

  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  void trend;

  let startDeg = -90;
  const paths = segments.map((seg) => {
    const sweep = (seg.value / total) * 360;
    const endDeg = startDeg + sweep - GAP_DEG;
    const d = sweep > GAP_DEG + 0.5 ? arcPath(cx, cy, outerR, innerR, startDeg, endDeg) : '';
    startDeg += sweep;
    return { d, color: seg.color };
  });

  return (
    <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} style={{ overflow: 'visible' }}>
      {paths.map((p, i) => p.d && <path key={i} d={p.d} fill={p.color} />)}
      <text
        x={cx}
        y={cy - 4}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize="18"
        fontWeight="800"
        fontFamily="'Plus Jakarta Sans', sans-serif"
        fill={POS_COLOR}
      >
        {Math.round((positive / total) * 100)}%
      </text>
      <text
        x={cx}
        y={cy + 13}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize="8.5"
        fontWeight="600"
        fontFamily="'Plus Jakarta Sans', sans-serif"
        fill="#9CA3AF"
      >
        positive
      </text>
    </svg>
  );
}

/* ─── Legend row ─────────────────────────────────────────────── */
interface LegendDotProps {
  color: string;
  label: string;
  value: number;
}

function LegendDot({ color, label, value }: LegendDotProps) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
      <span className="text-2xs text-muted-foreground">{label}</span>
      <span className="text-2xs font-bold text-foreground">{value}%</span>
    </div>
  );
}

export interface CommentItem {
  id: string;
  author: string;
  initials: string;
  avatarColor: string;
  timeAgo: string;
  text: string;
  commentSentiment?: 'positive' | 'neutral' | 'negative';
}

export interface TopicCommentData {
  id: string;
  name: string;
  category: string;
  sentiment: { positive: number; neutral: number; negative: number };
  platforms: { name: string; pct: number; color: string }[];
  trend: number;
  aiConfidence: number;
  mentions: number;
  status: 'healthy' | 'warning' | 'critical';
  comments: CommentItem[];
}

interface TopicCommentCardProps {
  topic: TopicCommentData;
}

export default function TopicCommentCard({ topic }: TopicCommentCardProps) {
  const [expanded, setExpanded] = useState(false);
  // Per-comment expand state — clicking one long comment expands only that comment.
  const [openComments, setOpenComments] = useState<Set<string>>(new Set());
  const toggleComment = (id: string) =>
    setOpenComments((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const visibleComments = expanded ? topic.comments : topic.comments.slice(0, 3);
  const hasMore = topic.comments.length > 3;

  return (
    <div className="bg-card border border-border rounded-xl p-4 flex flex-col card-shadow">
      {/* ── Topic name ── */}
      <div className="mb-3">
        <p className="text-sm font-bold text-foreground leading-snug">{topic.name}</p>
        <p className="text-2xs font-medium text-muted-foreground mt-0.5">{topic.category}</p>
      </div>

      {/* ── Donut chart ── */}
      <div className="flex justify-center mb-3">
        <DonutChart
          positive={topic.sentiment.positive}
          neutral={topic.sentiment.neutral}
          negative={topic.sentiment.negative}
          trend={topic.trend}
        />
      </div>

      {/* ── Sentiment legend ── */}
      <div className="flex flex-col gap-1 mb-3">
        <LegendDot color={POS_COLOR} label="Positive" value={topic.sentiment.positive} />
        <LegendDot color={NEU_COLOR} label="Neutral" value={topic.sentiment.neutral} />
        <LegendDot color={NEG_COLOR} label="Negative" value={topic.sentiment.negative} />
      </div>

      {/* ── Footer: mention count ── */}
      <div className="pt-2.5 border-t border-border mb-3">
        <p className="text-2xs text-muted-foreground tabular-nums text-center">
          {topic.mentions >= 1000 ? `${(topic.mentions / 1000).toFixed(1)}K` : topic.mentions}{' '}
          mentions
        </p>
      </div>

      {/* Comments Section */}
      <div>
        <p className="text-2xs font-bold text-muted-foreground uppercase tracking-wide mb-2.5">
          Recent Comments ({visibleComments.length} of {topic.comments.length.toLocaleString()})
        </p>
        <div
          className={`space-y-2 ${
            expanded ? 'max-h-80 overflow-y-auto scrollbar-thin pr-1' : ''
          }`}
        >
          {visibleComments.map((comment) => {
            let sentimentText = 'text-muted-foreground';
            if (comment.commentSentiment === 'positive') sentimentText = 'text-positive';
            else if (comment.commentSentiment === 'negative') sentimentText = 'text-negative';
            else if (comment.commentSentiment === 'neutral') sentimentText = 'text-warning';

            const isOpen = openComments.has(comment.id);
            const isLong = (comment.text || '').length > 60;

            return (
              <div
                key={comment.id}
                onClick={() => isLong && toggleComment(comment.id)}
                className={`bg-muted/40 rounded-lg p-2.5 ${isLong ? 'cursor-pointer hover:bg-muted/60' : ''}`}
              >
                <div className="flex items-start gap-1">
                  <p
                    className={`flex-1 text-sm text-foreground font-medium ${isOpen ? 'leading-relaxed' : 'line-clamp-1'}`}
                  >
                    &ldquo;{comment.text}&rdquo;
                  </p>
                  {isLong && (
                    <span className="shrink-0 text-xs font-bold text-primary select-none">
                      {isOpen ? '(–)' : '(…)'}
                    </span>
                  )}
                </div>
                <div className="flex justify-between items-center mt-1.5">
                  <span className={`text-[11px] font-bold tracking-wider uppercase ${sentimentText}`}>
                    {comment.commentSentiment || 'neutral'}
                  </span>
                  <span className="text-[11px] font-bold tracking-wider text-muted-foreground uppercase">
                    {comment.timeAgo}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Toggle */}
        {hasMore && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="mt-3 w-full flex items-center justify-center gap-1 text-xs font-semibold text-primary hover:underline transition-colors"
          >
            {expanded ? (
              <>
                COLLAPSE <ChevronUp size={14} />
              </>
            ) : (
              <>
                MORE COMMENTS ({topic.comments.length - 3}) <ChevronDown size={14} />
              </>
            )}
          </button>
        )}
      </div>
    </div>
  );
}
