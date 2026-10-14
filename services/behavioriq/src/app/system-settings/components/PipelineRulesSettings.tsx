'use client';

import React, { useEffect, useState } from 'react';
import { Calendar, Clock, RotateCcw, Save } from 'lucide-react';
import { toast } from 'sonner';
import { getPipelineSettings, updatePipelineSettings, validateCron } from '@/lib/api';
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

type FieldErrors = Partial<Record<'cron' | 'lookback' | 'form', string>>;

// Parse the hour out of a daily cron (`M H * * *`); default midnight.
function hourFromCron(cron: string): number {
  const parts = (cron || '').trim().split(/\s+/);
  const h = parseInt(parts[1], 10);
  return Number.isInteger(h) && h >= 0 && h <= 23 ? h : 0;
}

export default function PipelineRulesSettings() {
  const [settings, setSettings] = useState<any>(null);
  // Schedule is hours-only by design: the pipeline runs daily at a chosen hour,
  // so the user can never set a minute-level cadence. We always emit `0 H * * *`.
  const [scheduleHour, setScheduleHour] = useState(0);
  const [lookback, setLookback] = useState('30');
  const [nextRuns, setNextRuns] = useState<string[]>([]);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [saving, setSaving] = useState(false);

  const cron = `0 ${scheduleHour} * * *`;

  useEffect(() => {
    getPipelineSettings()
      .then((data) => {
        setSettings(data);
        setScheduleHour(hourFromCron(data.pipeline_schedule_cron || '0 0 * * *'));
        setLookback(String(data.pipeline_lookback_days || 30));
        setNextRuns(data.next_run_times || []);
      })
      .catch((error) => {
        setErrors({ form: getErrorMessage(error, 'Unable to load pipeline settings.') });
      });
  }, []);

  // Refresh the upcoming-runs preview whenever the chosen hour changes.
  useEffect(() => {
    let active = true;
    validateCron(`0 ${scheduleHour} * * *`)
      .then((res) => {
        if (active && res.valid) setNextRuns(res.next_runs || []);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [scheduleHour]);

  const validateFields = () => {
    const nextErrors: FieldErrors = {};
    const parsedLookback = Number(lookback);
    if (!lookback.trim()) {
      nextErrors.lookback = 'Lookback days is required.';
    } else if (!Number.isInteger(parsedLookback) || parsedLookback < 1 || parsedLookback > 365) {
      nextErrors.lookback = 'Enter a whole number between 1 and 365.';
    }
    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const handleSave = async () => {
    if (!validateFields()) return;

    setSaving(true);
    setErrors({});
    try {
      await updatePipelineSettings({
        schedule_cron: cron,
        lookback_days: parseInt(lookback, 10),
        run_on_startup: settings?.pipeline_run_on_startup ?? true,
      });
      toast.success('Pipeline settings saved');
    } catch (error) {
      const message = getErrorMessage(error, 'Unable to save pipeline settings.');
      setErrors(message.toLowerCase().includes('cron') ? { cron: message } : { form: message });
      toast.error('Pipeline settings were not saved');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setScheduleHour(hourFromCron(settings?.pipeline_schedule_cron || '0 0 * * *'));
    setLookback(String(settings?.pipeline_lookback_days || 30));
    setErrors({});
  };

  return (
    <div className="space-y-6">
      <SettingsPageHeader
        title="Pipeline Rules"
        description="Configure when the analysis pipeline runs and how much history each run processes."
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
        title="Ingestion Schedule"
        description="Define when the pipeline runs and how much historical data it processes."
        icon={<Clock size={18} />}
      >
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <SettingsField
            label="Run daily at"
            description="The pipeline runs once a day at this hour. Minute-level schedules aren't allowed."
            error={errors.cron}
          >
            <div className="relative">
              <select
                value={scheduleHour}
                onChange={(event) => setScheduleHour(Number(event.target.value))}
                className={`${inputClassName} appearance-none pr-10`}
              >
                {Array.from({ length: 24 }, (_, h) => (
                  <option key={h} value={h}>
                    {String(h).padStart(2, '0')}:00
                  </option>
                ))}
              </select>
              <Clock size={16} className="pointer-events-none absolute right-3 top-2.5 text-muted-foreground" />
            </div>
          </SettingsField>

          <SettingsField
            label="Lookback Days"
            description="Historical days to pull during each ingestion cycle."
            error={errors.lookback}
          >
            <div className="relative">
              <input
                type="number"
                min={1}
                max={365}
                value={lookback}
                onChange={(event) => setLookback(event.target.value)}
                className={`${inputClassName} pr-10`}
              />
              <Calendar size={16} className="absolute right-3 top-2.5 text-muted-foreground" />
            </div>
          </SettingsField>
        </div>

        <div className="mt-5 rounded-lg border border-border bg-muted/30 p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Next Runs
          </p>
          <p className="mt-2 text-sm font-medium text-foreground">
            {nextRuns.length > 0
              ? nextRuns.slice(0, 3).join(', ')
              : 'Upcoming runs will appear here.'}
          </p>
        </div>
      </SettingsCard>
    </div>
  );
}
