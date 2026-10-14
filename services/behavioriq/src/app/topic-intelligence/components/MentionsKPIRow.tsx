'use client';

import React from 'react';
import { MessageSquare, Gauge } from 'lucide-react';
import PlatformIcon from './PlatformIcon';

interface SentimentCounts {
  positive: number;
  neutral: number;
  negative: number;
}

interface MentionsKPIRowProps {
  total: number;
  sentiment: SentimentCounts;
  sources: { source: string; count: number }[];
  loading?: boolean;
}

const PLATFORM_LABEL: Record<string, string> = {
  facebook: 'Facebook',
  instagram: 'Instagram',
  twitter: 'Twitter',
  tiktok: 'TikTok',
};

function Card({ children }: { children: React.ReactNode }) {
  return <div className="panel px-5 py-5 flex flex-col">{children}</div>;
}

function CardLabel({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
        {icon}
      </span>
      <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
        {children}
      </span>
    </div>
  );
}

export default function MentionsKPIRow({ total, sentiment, sources, loading }: MentionsKPIRowProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="panel px-5 py-5">
            <div className="skeleton h-4 w-28 mb-3" />
            <div className="skeleton h-8 w-24" />
          </div>
        ))}
      </div>
    );
  }

  const sentTotal = sentiment.positive + sentiment.neutral + sentiment.negative;
  const pct = (n: number) => (sentTotal > 0 ? Math.round((n / sentTotal) * 100) : 0);
  const posPct = pct(sentiment.positive);
  const sourceTotal = sources.reduce((s, x) => s + x.count, 0);
  const topSources = [...sources].sort((a, b) => b.count - a.count).slice(0, 4);

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {/* Total comments */}
      <Card>
        <CardLabel icon={<MessageSquare size={15} />}>Total Comments</CardLabel>
        <span className="text-3xl font-black text-foreground tabular-nums leading-none tracking-tight">
          {total.toLocaleString()}
        </span>
        <span className="mt-2 text-xs text-muted-foreground">Analyzed in the latest run</span>
      </Card>

      {/* Average sentiment */}
      <Card>
        <CardLabel icon={<Gauge size={15} />}>Average Sentiment</CardLabel>
        <span className="text-3xl font-black tabular-nums leading-none tracking-tight" style={{ color: 'var(--positive)' }}>
          {posPct}%
        </span>
        <div className="mt-3 flex h-2 w-full overflow-hidden rounded-full bg-muted">
          <div style={{ width: `${pct(sentiment.positive)}%`, backgroundColor: 'var(--positive)' }} />
          <div style={{ width: `${pct(sentiment.neutral)}%`, backgroundColor: 'var(--warning)' }} />
          <div style={{ width: `${pct(sentiment.negative)}%`, backgroundColor: 'var(--negative)' }} />
        </div>
        <div className="mt-2 flex justify-between text-2xs font-semibold text-muted-foreground">
          <span style={{ color: 'var(--positive)' }}>{pct(sentiment.positive)}% pos</span>
          <span style={{ color: 'var(--warning)' }}>{pct(sentiment.neutral)}% neu</span>
          <span style={{ color: 'var(--negative)' }}>{pct(sentiment.negative)}% neg</span>
        </div>
      </Card>

      {/* Sources breakdown */}
      <Card>
        <CardLabel icon={<PlatformIcon platform={topSources[0]?.source || 'facebook'} size={20} />}>
          Sources
        </CardLabel>
        {topSources.length === 0 ? (
          <span className="text-sm text-muted-foreground">No sources</span>
        ) : (
          <div className="flex flex-col gap-2">
            {topSources.map((s) => {
              const p = sourceTotal > 0 ? Math.round((s.count / sourceTotal) * 100) : 0;
              return (
                <div key={s.source} className="flex items-center gap-2.5">
                  <PlatformIcon platform={s.source} size={22} />
                  <span className="text-xs font-semibold text-foreground capitalize w-20 truncate">
                    {PLATFORM_LABEL[s.source] || s.source}
                  </span>
                  <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${p}%`, backgroundColor: 'var(--primary)' }} />
                  </div>
                  <span className="text-xs font-bold text-foreground tabular-nums w-16 text-right">
                    {s.count.toLocaleString()}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}
