import type { Job, Label, Stats } from './types'

export const PAGE = 50

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    // FastAPI 的錯誤是 {"detail": ...}，撈得到就用它，撈不到就用狀態碼
    const detail = await res
      .json()
      .then((b) => (typeof b?.detail === 'string' ? b.detail : null))
      .catch(() => null)
    throw new Error(detail ?? `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export function listJobs(params: Record<string, string>, offset: number): Promise<Job[]> {
  const q = new URLSearchParams({
    ...params,
    limit: String(PAGE),
    offset: String(offset),
  })
  return json<Job[]>(`/api/jobs?${q}`)
}

export function getStats(): Promise<Stats> {
  return json<Stats>('/api/stats')
}

/**
 * label 跟 note 是同一次提交。空字串正規化成 null —— DB 裡不要同時存在
 * 兩種「沒理由」，之後撈分歧匯進 eval 考卷會多一個 case 要處理。
 *
 * 「一致就不留理由、換答案就不沿用舊的」是 queries.py 的 LABEL 那條 CASE 在管，
 * 前端不用也不該重算一次。
 */
export function setLabel(slug: string, label: Label | null, note: string): Promise<Job> {
  return json<Job>(`/api/jobs/${slug}/label`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ human_label: label, human_note: note.trim() || null }),
  })
}

export function setStar(slug: string, starred: boolean): Promise<Job> {
  return json<Job>(`/api/jobs/${slug}/star`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ starred }),
  })
}
