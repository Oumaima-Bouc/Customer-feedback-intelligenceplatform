'use client';

import React, { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown, Activity, Database, Gauge } from 'lucide-react';
import { getDashboardOverview, getDashboardSources } from '@/lib/api';
import PlatformIcon from '@/app/topic-intelligence/components/PlatformIcon';

interface StatCardProps {
  label: string;
  icon: React.ReactNode;
  value: React.ReactNode;
  delta?: { pct: number; suffix?: string; note: string };
  children?: React.ReactNode;
}

function StatCard({ label, icon, value, delta, children }: StatCardProps) {
  return (
    <div className="p-5">
      <div className="flex items-center gap-2 mb-3">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
          {icon}
        </span>
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
      </div>
      <div className="text-3xl font-extrabold tracking-tight text-foreground tabular-nums">
        {value}
      </div>
      {delta && (
        <div className="flex items-center gap-1.5 mt-1.5">
          <span className={delta.pct >= 0 ? 'badge-positive' : 'badge-negative'}>
            {delta.pct >= 0 ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
            {delta.pct >= 0 ? '+' : ''}
            {delta.pct}
            {delta.suffix ?? '%'}
          </span>
          <span className="text-xs text-muted-foreground">{delta.note}</span>
        </div>
      )}
      {children}
    </div>
  );
}

export default function KPIMetricsRow() {
  const [overview, setOverview] = useState<any>(null);
  const [sources, setSources] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      getDashboardOverview().then(setOverview).catch(() => {}),
      getDashboardSources().then(setSources).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="panel overflow-hidden">
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 divide-y md:divide-y-0 md:divide-x divide-border">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="p-5">
              <div className="skeleton h-4 w-28 mb-3" />
              <div className="skeleton h-8 w-20 mb-2" />
              <div className="skeleton h-4 w-24" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  const daily = overview?.daily_treatment || { count: 0, change_pct: 0 };
  const total = overview?.total_comments_scraped || 0;
  const sentiment = overview?.overall_sentiment || { positive_pct: 0, change_pct: 0 };
  const sentimentScore = Math.round(sentiment.positive_pct);
  const sentimentChange = sentiment.change_pct ?? 0;
  const topSource = (sources?.sources || [])[0];

  const fmtTotal = (n: number) => {
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
    return String(n);
  };

  return (
    <div className="panel overflow-hidden">
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 divide-y md:divide-y-0 md:divide-x divide-border">
        <StatCard
          label="Daily Treatment"
          icon={<Activity size={15} />}
          value={(daily.count ?? 0).toLocaleString()}
          delta={{ pct: daily.change_pct, note: 'vs previous run' }}
        />
        <StatCard
          label="System Total"
          icon={<Database size={15} />}
          value={fmtTotal(total)}
        />
        <StatCard
          label="Average Sentiment"
          icon={<Gauge size={15} />}
          value={`${sentimentScore}%`}
          delta={{ pct: sentimentChange, note: 'positive vs previous run' }}
        />
        <StatCard label="Top Source" icon={<TrendingUp size={15} />} value={
          topSource ? (
            <div className="flex items-center gap-3">
              <PlatformIcon platform={topSource.platform} size={38} />
              <div className="min-w-0">
                <span className="block truncate text-base font-bold text-foreground leading-tight">
                  {topSource.name}
                </span>
                <span className="text-xs font-normal text-muted-foreground">
                  {topSource.count.toLocaleString()} comments · {topSource.pct}%
                </span>
              </div>
            </div>
          ) : (
            <span className="text-sm text-muted-foreground">No sources</span>
          )
        } />
      </div>
    </div>
  );
}
