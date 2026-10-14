import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

export async function GET() {
  const filePath = path.join(process.cwd(), 'src/data/settings.json');
  try {
    const data = fs.readFileSync(filePath, 'utf8');
    return NextResponse.json(JSON.parse(data));
  } catch (_error) {
    return NextResponse.json({ error: 'Failed to read settings' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  const filePath = path.join(process.cwd(), 'src/data/settings.json');
  try {
    const currentData = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    const updates = await request.json();

    const newData = { ...currentData, ...updates };
    fs.writeFileSync(filePath, JSON.stringify(newData, null, 2));

    return NextResponse.json({ success: true, settings: newData });
  } catch (_error) {
    return NextResponse.json({ error: 'Failed to update settings' }, { status: 500 });
  }
}
