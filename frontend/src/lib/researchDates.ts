import type { WindowDates } from './explorer'

export function researchDateOptions(
  explorerMode: 'api' | 'fixture',
  syntheticApiTest: boolean,
  today: string,
  pilotWindow?: WindowDates,
) {
  if (explorerMode === 'api' && !syntheticApiTest && pilotWindow &&
      /^\d{4}-\d{2}-\d{2}$/.test(pilotWindow.start) &&
      /^\d{4}-\d{2}-\d{2}$/.test(pilotWindow.end) &&
      pilotWindow.start <= pilotWindow.end) {
    return {
      initialWindow: pilotWindow,
      presets: [{ label: 'Available data', ...pilotWindow }],
    }
  }
  const end = explorerMode === 'fixture' || syntheticApiTest ? '2025-12-31' : today
  const monthStart = (monthsBefore: number) => {
    const date = new Date(`${end}T12:00:00Z`)
    date.setUTCDate(1)
    date.setUTCMonth(date.getUTCMonth() - monthsBefore)
    return date.toISOString().slice(0, 10)
  }
  const presets: { label: string; start: string; end: string }[] = [
    { label: '1M', start: monthStart(0), end },
    { label: '3M', start: monthStart(2), end },
    { label: '1Y', start: monthStart(11), end },
  ]
  const initialWindow: WindowDates = { start: presets[0].start, end }
  return { initialWindow, presets }
}
