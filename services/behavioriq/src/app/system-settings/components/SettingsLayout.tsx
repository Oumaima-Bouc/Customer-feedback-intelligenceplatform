'use client';

import React, { useState } from 'react';
import { Cloud, Link, SlidersHorizontal, User } from 'lucide-react';
import AccountManagementSettings from './AccountManagementSettings';
import MetaConnectionsSettings from './MetaConnectionsSettings';
import PipelineRulesSettings from './PipelineRulesSettings';
import WordCloudSettings from './WordCloudSettings';

export const SettingsContext = React.createContext({
  isDirty: false,
  setDirty: (_val: boolean) => {},
});

const settingsNav = [
  { id: 'nav-account', label: 'Account Management', icon: User },
  { id: 'nav-meta-connections', label: 'Scraper Settings', icon: Link },
  { id: 'nav-pipeline-rules', label: 'Pipeline Rules', icon: SlidersHorizontal },
  { id: 'nav-word-cloud-settings', label: 'Word Cloud Settings', icon: Cloud },
];

const contentMap: Record<string, React.ReactNode> = {
  'nav-account': <AccountManagementSettings />,
  'nav-meta-connections': <MetaConnectionsSettings />,
  'nav-pipeline-rules': <PipelineRulesSettings />,
  'nav-word-cloud-settings': <WordCloudSettings />,
};

export default function SettingsLayout() {
  const [activeSection, setActiveSection] = useState('nav-account');
  const [isDirty, setDirty] = useState(false);

  return (
    <SettingsContext.Provider value={{ isDirty, setDirty }}>
      <div className="relative pb-10">
        <div className="mb-6 rounded-xl border border-border bg-card card-shadow">
          <div className="border-b border-border px-5 py-4">
            <h1 className="text-xl font-bold tracking-tight text-foreground">System Settings</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Configure account, data collection, processing, and visualization behavior.
            </p>
          </div>
          <nav className="flex w-full items-center gap-1 overflow-x-auto px-3">
            {settingsNav.map((item) => {
              const Icon = item.icon;
              const isActive = activeSection === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveSection(item.id)}
                  className={`-mb-px flex items-center gap-2 whitespace-nowrap border-b-2 px-4 py-3 text-sm font-semibold transition-colors ${
                    isActive
                      ? 'border-primary text-primary'
                      : 'border-transparent text-muted-foreground hover:border-border hover:text-foreground'
                  }`}
                >
                  <Icon size={16} className="flex-shrink-0" />
                  {item.label}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Content */}
        <div className="w-full fade-in" key={activeSection}>
          {contentMap[activeSection]}
        </div>
      </div>
    </SettingsContext.Provider>
  );
}
