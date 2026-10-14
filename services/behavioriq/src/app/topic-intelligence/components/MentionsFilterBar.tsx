'use client';

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { ChevronDown, Check, X, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import PlatformIcon from './PlatformIcon';

/* ─── Types ──────────────────────────────────────────────────── */

interface DropdownOption {
  value: string;
  label: string;
  icon?: React.ReactNode;
}

interface FilterDropdownProps {
  label: string;
  options: DropdownOption[];
  selected: string | null;
  onSelect: (value: string | null) => void;
}

/* ─── Sentiment icon helper ─────────────────────────────────── */

function SentimentIcon({ sentiment }: { sentiment: string }) {
  if (sentiment === 'Positive')
    return <TrendingUp size={16} style={{ color: 'var(--positive)' }} />;
  if (sentiment === 'Neutral') return <Minus size={16} style={{ color: 'var(--warning)' }} />;
  if (sentiment === 'Negative')
    return <TrendingDown size={16} style={{ color: 'var(--negative)' }} />;
  return null;
}

/* ─── Generic dropdown ───────────────────────────────────────── */

function FilterDropdown({ label, options, selected, onSelect }: FilterDropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  /* close on outside click */
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const selectedLabel = options.find((o) => o.value === selected)?.label ?? null;

  const handleSelect = useCallback(
    (value: string) => {
      onSelect(selected === value ? null : value);
      setOpen(false);
    },
    [selected, onSelect]
  );

  return (
    <div ref={ref} className="relative">
      {/* Trigger button */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex min-h-10 items-center gap-2 px-4 py-2 rounded-lg border text-sm font-semibold transition-all duration-150 min-w-[120px]"
        style={{
          borderColor: open || selected ? 'var(--primary)' : 'var(--border)',
          backgroundColor: open || selected ? 'rgba(14,95,168,0.05)' : 'var(--card)',
          color: selected ? 'var(--primary)' : 'var(--foreground)',
          boxShadow: open ? '0 0 0 3px rgba(14,95,168,0.10)' : 'none',
        }}
      >
        {/* Icon for currently selected option */}
        {selected && options.find((o) => o.value === selected)?.icon && (
          <span className="flex-shrink-0">{options.find((o) => o.value === selected)!.icon}</span>
        )}
        <span className="flex-1 text-left whitespace-nowrap">{selectedLabel ?? label}</span>
        {selected ? (
          <X
            size={14}
            className="flex-shrink-0 opacity-60 hover:opacity-100"
            onClick={(e) => {
              e.stopPropagation();
              onSelect(null);
            }}
          />
        ) : (
          <ChevronDown
            size={15}
            className="flex-shrink-0 text-muted-foreground transition-transform duration-200"
            style={{ transform: open ? 'rotate(180deg)' : 'rotate(0deg)' }}
          />
        )}
      </button>

      {/* Dropdown panel */}
      {open && (
        <div
          className="absolute top-full left-0 mt-2 z-50 bg-card border border-border rounded-xl overflow-hidden fade-in"
          style={{
            minWidth: 200,
            boxShadow: 'var(--shadow-popover)',
          }}
        >
          {options.map((option) => {
            const isSelected = selected === option.value;
            return (
              <button
                key={option.value}
                onClick={() => handleSelect(option.value)}
                className="w-full flex items-center gap-3 px-4 py-2.5 text-sm font-medium text-left transition-colors duration-100"
                style={{
                  backgroundColor: isSelected ? 'rgba(14,95,168,0.08)' : 'transparent',
                  color: isSelected ? 'var(--primary)' : 'var(--foreground)',
                }}
                onMouseEnter={(e) => {
                  if (!isSelected)
                    (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--muted)';
                }}
                onMouseLeave={(e) => {
                  if (!isSelected)
                    (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent';
                }}
              >
                {option.icon && <span className="flex-shrink-0">{option.icon}</span>}
                <span className="flex-1">{option.label}</span>
                {isSelected && <Check size={14} style={{ color: 'var(--primary)' }} />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ─── Filter options ─────────────────────────────────────────── */

const SOURCE_OPTIONS: DropdownOption[] = [
  { value: 'Twitter', label: 'Twitter', icon: <PlatformIcon platform="twitter" size={20} /> },
  { value: 'Facebook', label: 'Facebook', icon: <PlatformIcon platform="facebook" size={20} /> },
  { value: 'Instagram', label: 'Instagram', icon: <PlatformIcon platform="instagram" size={20} /> },
  { value: 'TikTok', label: 'TikTok', icon: <PlatformIcon platform="tiktok" size={20} /> },
];

const TOPIC_OPTIONS: DropdownOption[] = [
  { value: 'Product Quality', label: 'Product Quality' },
  { value: 'Customer Service', label: 'Customer Service' },
  { value: 'Delivery', label: 'Delivery' },
  { value: 'Ambiance', label: 'Ambiance' },
];

const SENTIMENT_OPTIONS: DropdownOption[] = [
  { value: 'Positive', label: 'Positive', icon: <SentimentIcon sentiment="Positive" /> },
  { value: 'Neutral', label: 'Neutral', icon: <SentimentIcon sentiment="Neutral" /> },
  { value: 'Negative', label: 'Negative', icon: <SentimentIcon sentiment="Negative" /> },
];

/* ─── Public component ───────────────────────────────────────── */

interface MentionsFilterBarProps {
  sourceFilter: string | null;
  topicFilter: string | null;
  sentimentFilter: string | null;
  availableTopics?: string[];
  availableSources?: string[];
  availableSentiments?: string[];
  onSourceChange: (v: string | null) => void;
  onTopicChange: (v: string | null) => void;
  onSentimentChange: (v: string | null) => void;
  totalCount: number;
  filteredCount: number;
}

export default function MentionsFilterBar({
  sourceFilter,
  topicFilter,
  sentimentFilter,
  availableTopics = [],
  availableSources = [],
  availableSentiments = [],
  onSourceChange,
  onTopicChange,
  onSentimentChange,
  totalCount,
  filteredCount,
}: MentionsFilterBarProps) {
  const hasActiveFilter = sourceFilter || topicFilter || sentimentFilter;

  const clearAll = () => {
    onSourceChange(null);
    onTopicChange(null);
    onSentimentChange(null);
  };

  const dynamicTopicOptions: DropdownOption[] =
    availableTopics.length > 0
      ? availableTopics.map((t) => ({ value: t, label: t }))
      : TOPIC_OPTIONS;

  // Source + sentiment options reflect only what the current run's comments contain.
  const dynamicSourceOptions: DropdownOption[] =
    availableSources.length > 0
      ? availableSources.map((s) => ({
          value: s,
          label: s,
          icon: <PlatformIcon platform={s.toLowerCase()} size={20} />,
        }))
      : SOURCE_OPTIONS;

  const dynamicSentimentOptions: DropdownOption[] =
    availableSentiments.length > 0
      ? availableSentiments.map((s) => ({ value: s, label: s, icon: <SentimentIcon sentiment={s} /> }))
      : SENTIMENT_OPTIONS;

  return (
    <div className="panel px-4 py-4 sm:px-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:flex-wrap lg:items-center">
        {/* Label */}
        <span className="text-xs font-bold uppercase tracking-wide text-muted-foreground mr-1">
          Filter by
        </span>

        {/* Source dropdown */}
        <FilterDropdown
          label="Source"
          options={dynamicSourceOptions}
          selected={sourceFilter}
          onSelect={onSourceChange}
        />

        {/* Topic dropdown */}
        <FilterDropdown
          label="Topic"
          options={dynamicTopicOptions}
          selected={topicFilter}
          onSelect={onTopicChange}
        />

        {/* Sentiment dropdown */}
        <FilterDropdown
          label="Sentiment"
          options={dynamicSentimentOptions}
          selected={sentimentFilter}
          onSelect={onSentimentChange}
        />

        {/* Clear all */}
        {hasActiveFilter && (
          <button
            onClick={clearAll}
            className="flex items-center gap-1 text-xs font-semibold transition-colors duration-150 ml-1"
            style={{ color: 'var(--negative)' }}
          >
            <X size={13} />
            Clear all
          </button>
        )}

        {/* Result count */}
        <div className="lg:ml-auto text-xs text-muted-foreground tabular-nums">
          Showing{' '}
          <span className="font-bold text-foreground">{filteredCount.toLocaleString()}</span> of{' '}
          <span className="font-bold text-foreground">{totalCount.toLocaleString()}</span> mentions
        </div>
      </div>
    </div>
  );
}
