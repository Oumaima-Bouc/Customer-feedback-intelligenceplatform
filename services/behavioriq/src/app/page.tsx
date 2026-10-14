'use client';

import React from 'react';
import AppLayout from '@/components/AppLayout';
import KPIMetricsRow from './components/KPIMetricsRow';
import WordCloudPanel from './components/WordCloudPanel';
import TopicTrendChart from './components/TopicTrendChart';
import TopicSentimentGrid from './components/TopicSentimentGrid';

export default function AnalyticsDashboardPage() {
  return (
    <AppLayout>
      <div className="space-y-6">
        <KPIMetricsRow />
        <WordCloudPanel />
        <TopicTrendChart />
        <TopicSentimentGrid />
      </div>
    </AppLayout>
  );
}
