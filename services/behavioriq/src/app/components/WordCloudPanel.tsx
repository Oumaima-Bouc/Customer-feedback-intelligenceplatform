'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Info } from 'lucide-react';
import { getWordCloud } from '@/lib/api';

interface WordEntry {
  id: string;
  word: string;
  weight: number;
  rotate: boolean;
  sentiment: { positive: number; neutral: number; negative: number };
  mentions: number;
  trend: number;
}

// Color palette: Algérie Télécom blue/green family (heaviest words = boldest brand tones).
const getColor = (weightScale: number, idx: number): string => {
  const primaryColors = ['#0b4a82', '#0e5fa8', '#1c8a3c', '#176b30']; // deep blues + greens
  const secondaryColors = ['#1577ba', '#2f9e44', '#0e7490', '#2563eb']; // blues, greens, teal
  const tertiaryColors = ['#3a9e35', '#0e5fa8', '#0d9488', '#1c8a3c']; // greens + blues
  const baseColors = ['#60a5fa', '#34d399', '#5fb030', '#38bdf8', '#22c55e']; // lighter blue/green variants

  if (weightScale >= 9) return primaryColors[idx % primaryColors.length];
  if (weightScale >= 7) return secondaryColors[idx % secondaryColors.length];
  if (weightScale >= 5) return tertiaryColors[idx % tertiaryColors.length];
  return baseColors[idx % baseColors.length];
};

interface PlacedWord {
  entry: WordEntry;
  x: number;
  y: number;
  w: number;
  h: number;
  color: string;
  fontSize: number;
  fontWeight: number;
}

// Ellipse containment check — wide ellipse shape matching reference
function insideEllipse(
  cx: number,
  cy: number,
  rx: number,
  ry: number,
  x: number,
  y: number,
  w: number,
  h: number
): boolean {
  // Check all 4 corners of the word bounding box
  const points = [
    [x, y],
    [x + w, y],
    [x, y + h],
    [x + w, y + h],
    [x + w / 2, y],
    [x + w / 2, y + h],
  ];
  for (const [px, py] of points) {
    const dx = (px - cx) / rx;
    const dy = (py - cy) / ry;
    if (dx * dx + dy * dy > 1) return false;
  }
  return true;
}

// Check overlap between two rectangles — generous padding prevents visual collisions
function overlaps(a: PlacedWord, bx: number, by: number, bw: number, bh: number): boolean {
  const padX = 14; // horizontal breathing room
  const padY = 8; // vertical breathing room
  return !(
    a.x + a.w + padX < bx ||
    bx + bw + padX < a.x ||
    a.y + a.h + padY < by ||
    by + bh + padY < a.y
  );
}

// Measure text width — calibrated for Plus Jakarta Sans
// Uses a larger multiplier + fixed buffer to match actual glyph widths
function measureText(text: string, fontSize: number, fontWeight: number): { w: number; h: number } {
  // Per-character width: heavier weights have wider glyphs
  const charWidth = fontSize * (fontWeight >= 700 ? 0.65 : 0.6);
  // Add a fixed per-word buffer (ascenders, descenders, kerning)
  const buffer = fontSize * 0.8;
  return { w: text.length * charWidth + buffer, h: fontSize * 1.4 };
}

// Archimedean spiral placement — words only, no rotation
function placeWords(words: WordEntry[], containerW: number, containerH: number): PlacedWord[] {
  const placed: PlacedWord[] = [];
  const cx = containerW / 2;
  const cy = containerH / 2;
  // Shrink the ellipse slightly so words don't clip the edges
  const rx = containerW * 0.46;
  const ry = containerH * 0.44;

  // Largest words placed first so they anchor the centre
  const sorted = [...words].sort((a, b) => b.mentions - a.mentions);
  const maxMentions = sorted.length > 0 ? sorted[0].mentions : 1;
  const minMentions = sorted.length > 0 ? sorted[sorted.length - 1].mentions : 0;

  for (let i = 0; i < sorted.length; i++) {
    const entry = sorted[i];

    // Scale size by frequency (mentions) instead of the old fixed weight 1-10 string
    // Calculate relative frequency 0..1 then map to a base size range 14..72
    const freqRatio = (entry.mentions - minMentions) / Math.max(1, maxMentions - minMentions);
    const fontSize = 14 + (72 - 14) * freqRatio;

    // Weight can still act as a pseudo-categorical fallback, or freqRatio can determine font weight
    const fontWeight =
      freqRatio >= 0.8 ? 900 : freqRatio >= 0.5 ? 700 : freqRatio >= 0.2 ? 600 : 500;
    const color = getColor(Math.round(freqRatio * 10), i);

    // All words are horizontal — rotation caused bounding-box mismatches
    const dims = measureText(entry.word, fontSize, fontWeight);

    let placed_flag = false;

    // Archimedean spiral: tighter angle steps at small radii, coarser further out
    for (let radius = 0; radius < Math.max(rx, ry); radius += 3) {
      const circumference = Math.max(1, 2 * Math.PI * radius);
      const steps = Math.max(12, Math.floor(circumference / 5));
      for (let step = 0; step < steps; step++) {
        const angle = (step / steps) * 2 * Math.PI + i * 0.618; // golden-ratio offset
        const tx = cx + radius * Math.cos(angle) - dims.w / 2;
        const ty = cy + radius * Math.sin(angle) - dims.h / 2;

        if (!insideEllipse(cx, cy, rx, ry, tx, ty, dims.w, dims.h)) continue;

        let hasOverlap = false;
        for (const p of placed) {
          if (overlaps(p, tx, ty, dims.w, dims.h)) {
            hasOverlap = true;
            break;
          }
        }

        if (!hasOverlap) {
          placed.push({ entry, x: tx, y: ty, w: dims.w, h: dims.h, color, fontSize, fontWeight });
          placed_flag = true;
          break;
        }
      }
      if (placed_flag) break;
    }
  }

  // Adjust placements to ensure the *exact* computed bounding box is perfectly centered in the SVG
  if (placed.length > 0) {
    let minX = Infinity,
      minY = Infinity;
    let maxX = -Infinity,
      maxY = -Infinity;

    placed.forEach((p) => {
      if (p.x < minX) minX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.x + p.w > maxX) maxX = p.x + p.w;
      if (p.y + p.h > maxY) maxY = p.y + p.h;
    });

    const actualCx = (minX + maxX) / 2;
    const actualCy = (minY + maxY) / 2;

    const offsetX = cx - actualCx;
    const offsetY = cy - actualCy;

    placed.forEach((p) => {
      p.x += offsetX;
      p.y += offsetY;
    });
  }

  return placed;
}

export default function WordCloudPanel() {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [placedWords, setPlacedWords] = useState<PlacedWord[]>([]);
  const [tooltipWord, setTooltipWord] = useState<WordEntry | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [loading, setLoading] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);

  const CONTAINER_W = 1200;
  const CONTAINER_H = 440;

  useEffect(() => {
    getWordCloud()
      .then((data: any) => {
        const words = (data.words || []).map((w: any, i: number) => ({
          id: `w${i}`,
          word: w.word,
          weight: Math.min(10, Math.max(1, Math.round((w.frequency || 1) / 100))),
          rotate: false,
          sentiment: {
            positive: Math.round(w.positive_pct || 33),
            neutral: Math.round(w.neutral_pct || 34),
            negative: Math.round(w.negative_pct || 33),
          },
          mentions: w.frequency || 100,
          trend: 0,
        }));
        setPlacedWords(words.length > 0 ? placeWords(words, CONTAINER_W, CONTAINER_H) : []);
      })
      .catch(() => setPlacedWords([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="panel p-5 sm:p-6 h-full min-h-[440px] lg:min-h-[500px] flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <h2 className="section-title">Intelligence Word Cloud</h2>
          <Info size={13} className="text-muted-foreground cursor-help" />
        </div>
      </div>

      {/* Word Cloud Container */}
      <div
        ref={containerRef}
        className="relative w-full overflow-hidden flex-grow flex items-center justify-center rounded-lg bg-muted/20 -mt-2"
        style={{ height: `${CONTAINER_H}px` }}
      >
        {loading && <div className="skeleton absolute inset-3 rounded-lg" />}
        {!loading && placedWords.length === 0 && (
          <div className="text-center">
            <p className="text-sm font-bold text-foreground">No words to track</p>
            <p className="text-xs text-muted-foreground mt-1">
              Add words in Settings → Word Cloud, or wait for the next analysed run.
            </p>
          </div>
        )}
        {/* SVG-based word cloud for precise placement */}
        <svg
          width="100%"
          height={CONTAINER_H}
          viewBox={`0 0 ${CONTAINER_W} ${CONTAINER_H}`}
          preserveAspectRatio="xMidYMid meet"
          style={{ display: 'block' }}
        >
          {placedWords.map((pw) => {
            const isDimmed = hoveredId !== null && hoveredId !== pw.entry.id;
            const isHovered = hoveredId === pw.entry.id;

            // All words are horizontal — text baseline sits at 78% of the box height
            const textX = pw.x + pw.w / 2;
            const textY = pw.y + pw.h * 0.78;

            return (
              <text
                key={pw.entry.id}
                x={textX}
                y={textY}
                fontSize={isHovered ? pw.fontSize * 1.06 : pw.fontSize}
                fontWeight={pw.fontWeight}
                fontFamily="'Plus Jakarta Sans', 'Inter', sans-serif"
                fill={isDimmed ? `${pw.color}40` : pw.color}
                textAnchor="middle"
                style={{
                  cursor: 'pointer',
                  transition: 'fill 180ms ease, font-size 180ms ease',
                  userSelect: 'none',
                }}
                onMouseEnter={(e) => {
                  setHoveredId(pw.entry.id);
                  setTooltipWord(pw.entry);
                  const rect = containerRef.current?.getBoundingClientRect();
                  if (rect) {
                    const svgEl = e.currentTarget.closest('svg') as SVGSVGElement;
                    const svgRect = svgEl?.getBoundingClientRect();
                    if (svgRect) {
                      const scaleX = svgRect.width / CONTAINER_W;
                      const scaleY = svgRect.height / CONTAINER_H;
                      setTooltipPos({
                        x: pw.x * scaleX,
                        y: pw.y * scaleY,
                      });
                    }
                  }
                }}
                onMouseLeave={() => {
                  setHoveredId(null);
                  setTooltipWord(null);
                }}
              >
                {pw.entry.word}
              </text>
            );
          })}
        </svg>

        {/* Tooltip — frequency only */}
        {tooltipWord && (
          <div
            className="absolute z-20 pointer-events-none chart-tooltip-card fade-in"
            style={{
              left: Math.min(tooltipPos.x, CONTAINER_W - 180),
              top: Math.max(tooltipPos.y - 70, 0),
            }}
          >
            <div className="font-bold text-sm text-foreground">{tooltipWord.word}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              <span className="font-semibold text-foreground tabular-nums">
                {tooltipWord.mentions.toLocaleString()}
              </span>{' '}
              {tooltipWord.mentions === 1 ? 'occurrence' : 'occurrences'}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
