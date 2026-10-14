import React from 'react';
import AppLayout from '@/components/AppLayout';
import TopicCommentsGrid from './components/TopicCommentsGrid';

export default function TopicCommentsPage() {
  return (
    <AppLayout>
      <div className="space-y-5">
        <TopicCommentsGrid />
      </div>
    </AppLayout>
  );
}
