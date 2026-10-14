'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { getTopicCards } from '@/lib/api';

/* ─── Types ──────────────────────────────────────────────────── */

interface TopicCard {
  id: string;
  name: string;
  category: string;
  sentiment: { positive: number; neutral: number; negative: number };
  platforms: { name: string; pct: number; color: string }[];
  trend: number;
  aiConfidence: number;
  mentions: number;
  status: 'healthy' | 'warning' | 'critical';
}

const CATEGORY_MAP: Record<string, string> = {
  pricing: 'Revenue Risk',
  delivery: 'Operations',
  quality: 'Product Feedback',
  support: 'CX Operations',
  loyalty: 'Brand Health',
};

function toStatus(pos: number, neg: number): 'healthy' | 'warning' | 'critical' {
  if (neg > 40) return 'critical';
  if (neg > 20 || pos < 40) return 'warning';
  return 'healthy';
}

export default function TopicSentimentGrid() {
  const [topicCards, setTopicCards] = useState<TopicCard[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getTopicCards()
      .then((data: any) => {
        const cards = (data.topics || []).map((t: any, i: number) => {
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
                    : s.source === 'tiktok'
                      ? 'TT'
                      : s.source.substring(0, 2).toUpperCase(),
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
            category: CATEGORY_MAP[t.topic.toLowerCase()] || 'General',
            sentiment,
            platforms: sources,
            trend: 0,
            aiConfidence: 90,
            mentions: t.comment_count || 0,
            status: toStatus(sentiment.positive, sentiment.negative),
          };
        });
        setTopicCards(cards);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div>
        <div className="mb-4">
          <div className="skeleton h-5 w-40 mb-2" />
          <div className="skeleton h-4 w-64" />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-[280px] panel skeleton" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between mb-4">
        <div>
          <h2 className="section-title">Topic Sentiment</h2>
          <p className="section-subtitle">Fast scan of leading topics and sentiment mix.</p>
        </div>
        <Link
          href="/topic-comments"
          className="text-xs font-bold text-primary hover:underline transition-colors"
        >
          View all topics →
        </Link>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {topicCards.slice(0, 3).map((card) => {
          return (
            <Link
              href="/topic-comments"
              key={card.id}
              className="panel p-5 cursor-pointer flex flex-col"
            >
              {/* ── Topic name (fully displayed, no truncation) ── */}
              <div className="mb-4">
                <p className="text-sm font-bold text-foreground leading-snug break-words">
                  {card.name}
                </p>
                <p className="text-2xs text-muted-foreground mt-0.5 break-words">{card.category}</p>
              </div>

              {/* ── Donut chart ── */}
              <div className="flex justify-center mb-4">
                <DonutChart
                  positive={card.sentiment.positive}
                  neutral={card.sentiment.neutral}
                  negative={card.sentiment.negative}
                  trend={card.trend}
                />
              </div>

              {/* ── Sentiment legend ── */}
              <div className="flex flex-col gap-1.5 mb-4">
                <LegendDot color={POS_COLOR} label="Positive" value={card.sentiment.positive} />
                <LegendDot color={NEU_COLOR} label="Neutral" value={card.sentiment.neutral} />
                <LegendDot color={NEG_COLOR} label="Negative" value={card.sentiment.negative} />
              </div>

              {/* ── Footer: mention count ── */}
              <div className="mt-auto pt-3 border-t border-border">
                <p className="text-xs text-muted-foreground tabular-nums text-center">
                  {card.mentions >= 1000 ? `${(card.mentions / 1000).toFixed(1)}K` : card.mentions}{' '}
                  mentions
                </p>
              </div>
            </Link>
          );
        })}

        {/* View All Card */}
        <Link
          href="/topic-comments"
          className="rounded-xl border border-border border-dashed bg-card/70 p-5 hover:bg-muted/50 transition-all duration-200 flex flex-col items-center justify-center gap-3 text-center"
        >
          <div className="w-12 h-12 rounded-full bg-primary/10 text-primary flex items-center justify-center mb-2">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M5 12h14" />
              <path d="m12 5 7 7-7 7" />
            </svg>
          </div>
          <div>
            <p className="font-semibold text-foreground text-sm">View All Topics</p>
            <p className="text-xs text-muted-foreground mt-1">See detailed sentiment & comments</p>
          </div>
        </Link>
      </div>
    </div>
  );
}

/* ─── Sentiment colours (hex — needed for SVG fill) ─────────── */

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
  const SIZE = 130;
  const cx = SIZE / 2;
  const cy = SIZE / 2;
  const outerR = 56;
  const innerR = 36;
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
      {/* Segments */}
      {paths.map((p, i) => p.d && <path key={i} d={p.d} fill={p.color} />)}

      {/* Centre: dominant positive share */}
      <text
        x={cx}
        y={cy - 5}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize="17"
        fontWeight="800"
        fontFamily="'Plus Jakarta Sans', sans-serif"
        fill={POS_COLOR}
      >
        {Math.round((positive / total) * 100)}%
      </text>

      {/* Centre: label */}
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
