'use client';

import React, { useEffect, useState } from 'react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  TooltipProps,
} from 'recharts';
import { Info } from 'lucide-react';
import { getTopicsTrend } from '@/lib/api';

const COLORS = ['#0e5fa8', '#1c8a3c', '#1577ba', '#0e7490', '#b9730a'];
const GRADIENTS = ['#7fb3e0', '#7fce92', '#7fc4e0', '#7fc9d2', '#e0c08a'];

interface TopicDef {
  key: string;
  label: string;
  color: string;
  gradientId: string;
  gradientColor: string;
  data: number[];
}

export default function TopicTrendChart() {
  const [topics, setTopics] = useState<TopicDef[]>([]);
  const [dayLabels, setDayLabels] = useState<string[]>([]);
  const [avgValue, setAvgValue] = useState(0);
  const [activeTopics, setActiveTopics] = useState<Set<string>>(new Set());
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  useEffect(() => {
    getTopicsTrend(7)
      .then((data: any) => {
        const dates = data.dates || [];
        const tps = (data.topics || []).map((t: any, i: number) => ({
          key: t.name.replace(/\s+/g, '-').toLowerCase(),
          label: t.name,
          color: COLORS[i % COLORS.length],
          gradientId: `grad_${i}`,
          gradientColor: GRADIENTS[i % GRADIENTS.length],
          data: t.data || [],
        }));
        const avg = tps.length
          ? Math.round(
              tps.reduce(
                (s: number, t: TopicDef) =>
                  s +
                  t.data.reduce((a: number, b: number) => a + b, 0) / Math.max(1, t.data.length),
                0
              ) / Math.max(1, tps.length)
            )
          : 0;
        setTopics(tps);
        setDayLabels(dates);
        setAvgValue(avg);
        if (tps.length) {
          setActiveTopics(new Set(tps.slice(0, 3).map((t: TopicDef) => t.key)));
        }
      })
      .catch(() => {});
  }, []);

  const chartData = dayLabels.map((day: string, i: number) => {
    const point: Record<string, number | string> = { day };
    topics.forEach((t) => {
      point[t.key] = t.data[i] ?? 0;
    });
    return point;
  });

  const CustomTooltip = ({ active, payload }: TooltipProps<number, string>) => {
    if (!active || !payload || !payload.length) return null;
    return (
      <div
        style={{
          background: '#fff',
          border: '1px solid #E5E7EB',
          borderRadius: 12,
          padding: '12px 16px',
          boxShadow: '0 4px 20px rgba(0,0,0,0.12)',
          minWidth: 200,
        }}
      >
        {payload.map((entry) => {
          const topic = topics.find((t) => t.key === entry.dataKey);
          if (!topic) return null;
          const val = entry.value as number;
          return (
            <div
              key={entry.dataKey}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: 24,
                marginBottom: 4,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: 2,
                    backgroundColor: topic.color,
                    display: 'inline-block',
                  }}
                />
                <span style={{ fontSize: 13, fontWeight: 600, color: '#111827' }}>
                  {topic.label}
                </span>
              </div>
              <span style={{ fontSize: 13, fontWeight: 700, color: topic.color }}>
                {val >= 1000 ? `${(val / 1000).toFixed(1)}K` : val}
              </span>
            </div>
          );
        })}
      </div>
    );
  };

  const AvgLabel = (props: {
    viewBox?: { x: number; y: number; width: number; height: number };
  }) => {
    const { viewBox } = props;
    if (!viewBox) return null;
    const { x, y } = viewBox;
    return (
      <g>
        <rect x={x - 2} y={y - 11} width={36} height={20} rx={4} fill="#111827" />
        <polygon
          points={`${x + 34},${y - 1} ${x + 40},${y - 1} ${x + 37},${y + 3}`}
          fill="#111827"
        />
        <text x={x + 16} y={y + 3} textAnchor="middle" fill="#fff" fontSize={11} fontWeight={600}>
          Avg
        </text>
      </g>
    );
  };

  const toggleTopic = (key: string) => {
    setActiveTopics((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        if (next.size > 1) next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  return (
    <div className="panel p-5 h-full">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <h2 className="section-title">Dynamic Topic Tracker</h2>
          <Info size={13} className="text-muted-foreground cursor-help" />
        </div>
      </div>

      <div className="h-[260px] rounded-lg bg-muted/10 p-1">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={chartData}
            margin={{ top: 10, right: 10, bottom: 0, left: 0 }}
            onMouseMove={(state) => {
              if (state.activeTooltipIndex !== undefined) {
                setActiveIndex(state.activeTooltipIndex);
              }
            }}
            onMouseLeave={() => setActiveIndex(null)}
          >
            <defs>
              {topics.map((t) => (
                <linearGradient key={t.gradientId} id={t.gradientId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={t.gradientColor} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={t.gradientColor} stopOpacity={0.03} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" vertical={true} />
            <XAxis
              dataKey="day"
              tick={{ fontSize: 11, fill: '#6B7280' }}
              tickLine={false}
              axisLine={{ stroke: '#E5E7EB' }}
            />
            <YAxis
              tick={{ fontSize: 11, fill: '#6B7280' }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: number) =>
                v === 0 ? '0' : v >= 1000 ? `${(v / 1000).toFixed(0)}000` : String(v)
              }
            />
            <Tooltip content={<CustomTooltip />} cursor={false} />
            <ReferenceLine
              y={avgValue}
              stroke="#9CA3AF"
              strokeDasharray="4 4"
              strokeWidth={1.5}
              label={<AvgLabel />}
            />
            {activeIndex !== null && (
              <ReferenceLine
                x={chartData[activeIndex]?.day as string}
                stroke="#111827"
                strokeDasharray="5 4"
                strokeWidth={1.5}
              />
            )}
            {topics.map((t) =>
              activeTopics.has(t.key) ? (
                <Area
                  key={t.key}
                  type="stepAfter"
                  dataKey={t.key}
                  stroke={t.color}
                  strokeWidth={2}
                  fill={`url(#${t.gradientId})`}
                  dot={false}
                  activeDot={{ r: 5, fill: '#fff', stroke: t.color, strokeWidth: 2 }}
                />
              ) : null
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="flex flex-wrap items-center gap-2 mt-4 pt-3 border-t border-border">
        {topics.map((t) => {
          const isActive = activeTopics.has(t.key);
          return (
            <button
              key={t.key}
              onClick={() => toggleTopic(t.key)}
              className="flex min-h-8 items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-bold transition-all duration-150 hover:-translate-y-0.5"
              style={{
                backgroundColor: isActive ? `${t.color}18` : '#F3F4F6',
                color: isActive ? t.color : '#9CA3AF',
                border: `1.5px solid ${isActive ? t.color : '#E5E7EB'}`,
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 2,
                  backgroundColor: isActive ? t.color : '#D1D5DB',
                  display: 'inline-block',
                  flexShrink: 0,
                }}
              />
              {t.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
