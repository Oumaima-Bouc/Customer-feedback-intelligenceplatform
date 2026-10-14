'use client';

import React, { useEffect, useState } from 'react';
import { Cloud, Eye, Plus, RotateCcw, Save, X } from 'lucide-react';
import { toast } from 'sonner';
import {
  addWordCloudWord,
  getWordCloud,
  getWordCloudSettings,
  removeWordCloudWord,
  updateWordCloudSettings,
} from '@/lib/api';
import {
  getErrorMessage,
  inputClassName,
  PrimaryButton,
  SecondaryButton,
  SettingsAlert,
  SettingsCard,
  SettingsField,
  SettingsPageHeader,
} from './settings-ui';

type FieldErrors = Partial<Record<'newWord' | 'maxWords' | 'minFreq' | 'form', string>>;

export default function WordCloudSettings() {
  const [settings, setSettings] = useState<any>(null);
  const [newWord, setNewWord] = useState('');
  const [maxWords, setMaxWords] = useState('50');
  const [minFreq, setMinFreq] = useState('5');
  const [errors, setErrors] = useState<FieldErrors>({});
  const [saving, setSaving] = useState(false);
  const [adding, setAdding] = useState(false);
  const [preview, setPreview] = useState<any[]>([]);
  const [previewLoading, setPreviewLoading] = useState(true);

  const loadSettings = () =>
    getWordCloudSettings()
      .then((data) => {
        setSettings(data);
        setMaxWords(String(data.settings?.max_words || 50));
        setMinFreq(String(data.settings?.min_frequency || 5));
      })
      .catch((error) => {
        setErrors({ form: getErrorMessage(error, 'Unable to load word cloud settings.') });
      });

  // Preview the exact words currently rendered on the dashboard cloud.
  const loadPreview = () => {
    setPreviewLoading(true);
    return getWordCloud()
      .then((data) => setPreview(data.words || []))
      .catch(() => setPreview([]))
      .finally(() => setPreviewLoading(false));
  };

  useEffect(() => {
    loadSettings();
    loadPreview();
  }, []);

  const curated = settings?.curated_words || [];

  const validateSettings = () => {
    const nextErrors: FieldErrors = {};
    const max = Number(maxWords);
    const min = Number(minFreq);

    if (!Number.isInteger(max) || max < 1 || max > 250) {
      nextErrors.maxWords = 'Enter a whole number between 1 and 250.';
    }
    if (!Number.isInteger(min) || min < 1 || min > 1000) {
      nextErrors.minFreq = 'Enter a whole number between 1 and 1,000.';
    }

    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const handleAddWord = async () => {
    const word = newWord.trim();
    if (!word) {
      setErrors({ newWord: 'Enter a keyword before adding it.' });
      return;
    }
    if (curated.some((item: any) => item.word?.toLowerCase() === word.toLowerCase())) {
      setErrors({ newWord: 'This keyword already exists.' });
      return;
    }

    setAdding(true);
    setErrors({});
    try {
      await addWordCloudWord(word);
      setNewWord('');
      await Promise.all([loadSettings(), loadPreview()]);
      toast.success('Keyword added');
    } catch (error) {
      setErrors({ newWord: getErrorMessage(error, 'Unable to add this keyword.') });
    } finally {
      setAdding(false);
    }
  };

  const handleRemoveWord = async (word: string) => {
    setErrors({});
    try {
      await removeWordCloudWord(word);
      await Promise.all([loadSettings(), loadPreview()]);
      toast.success('Keyword removed');
    } catch (error) {
      setErrors({ form: getErrorMessage(error, 'Unable to remove this keyword.') });
    }
  };

  const handleSave = async () => {
    if (!validateSettings()) return;

    setSaving(true);
    setErrors({});
    try {
      await updateWordCloudSettings({
        max_words: parseInt(maxWords, 10),
        min_frequency: parseInt(minFreq, 10),
      });
      await loadPreview();
      toast.success('Word cloud settings saved');
    } catch (error) {
      const message = getErrorMessage(error, 'Unable to save word cloud settings.');
      setErrors(
        message.toLowerCase().includes('frequency') ? { minFreq: message } : { form: message }
      );
      toast.error('Word cloud settings were not saved');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setMaxWords(String(settings?.settings?.max_words || 50));
    setMinFreq(String(settings?.settings?.min_frequency || 5));
    setErrors({});
  };

  return (
    <div className="space-y-6">
      <SettingsPageHeader
        title="Word Cloud Settings"
        description="Tune keyword curation and rendering thresholds used by the intelligence word cloud."
        action={
          <div className="flex gap-3">
            <SecondaryButton onClick={handleReset}>
              <RotateCcw size={16} />
              Reset
            </SecondaryButton>
            <PrimaryButton onClick={handleSave} loading={saving}>
              <Save size={16} />
              Save Changes
            </PrimaryButton>
          </div>
        }
      />

      {errors.form && <SettingsAlert tone="danger">{errors.form}</SettingsAlert>}

      <SettingsCard
        title="Live Preview"
        description="Exactly the words currently shown on the dashboard cloud, with the active thresholds applied."
        icon={<Eye size={18} />}
      >
        <div className="flex min-h-[260px] items-center justify-center rounded-lg border border-border bg-muted/20 p-8">
          {previewLoading ? (
            <div className="skeleton h-40 w-full rounded-lg" />
          ) : preview.length === 0 ? (
            <div className="text-center">
              <p className="text-sm font-bold text-foreground">No words to track</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Add keywords below, or lower the minimum frequency.
              </p>
            </div>
          ) : (
            <div className="flex max-w-4xl flex-wrap items-center justify-center gap-x-7 gap-y-5">
              {preview.slice(0, 18).map((item: any, index: number) => (
                <span
                  key={`${item.word}-${index}`}
                  className="leading-none"
                  style={{
                    fontSize: `${Math.max(14, 44 - index * 2)}px`,
                    fontWeight: index < 3 ? 800 : index < 7 ? 700 : 600,
                    color: [
                      '#0e5fa8',
                      '#1c8a3c',
                      '#1577ba',
                      '#2f9e44',
                      '#0b4a82',
                      '#0e7490',
                      '#176b30',
                      '#2563eb',
                    ][index % 8],
                  }}
                >
                  {item.word}
                </span>
              ))}
            </div>
          )}
        </div>
      </SettingsCard>

      <SettingsCard
        title="Configuration"
        description="Control which words are emphasized and the minimum frequency required for inclusion."
        icon={<Cloud size={18} />}
      >
        <div className="space-y-6">
          <SettingsField
            label="Curated Keywords"
            description="Press Enter or use Add to include a keyword in the visualization engine."
            error={errors.newWord}
          >
            <div className="rounded-lg border border-border bg-card p-2">
              <div className="mb-2 flex flex-wrap gap-2">
                {curated.map((item: any) => (
                  <span
                    key={item.word}
                    className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary"
                  >
                    {item.word}
                    <button
                      type="button"
                      onClick={() => handleRemoveWord(item.word)}
                      className="rounded-full p-0.5 hover:bg-primary/15"
                      aria-label={`Remove ${item.word}`}
                    >
                      <X size={13} />
                    </button>
                  </span>
                ))}
              </div>
              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  type="text"
                  value={newWord}
                  onChange={(event) => setNewWord(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      handleAddWord();
                    }
                  }}
                  placeholder="Add keyword..."
                  className={inputClassName}
                />
                <SecondaryButton onClick={handleAddWord} disabled={adding}>
                  <Plus size={16} />
                  {adding ? 'Adding...' : 'Add'}
                </SecondaryButton>
              </div>
            </div>
          </SettingsField>

          <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
            <SettingsField label="Minimum Frequency" error={errors.minFreq}>
              <input
                type="number"
                min={1}
                value={minFreq}
                onChange={(event) => setMinFreq(event.target.value)}
                className={inputClassName}
              />
            </SettingsField>
            <SettingsField label="Maximum Words" error={errors.maxWords}>
              <input
                type="number"
                min={1}
                value={maxWords}
                onChange={(event) => setMaxWords(event.target.value)}
                className={inputClassName}
              />
            </SettingsField>
          </div>
        </div>
      </SettingsCard>
    </div>
  );
}
