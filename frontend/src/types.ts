/** 欄位對齊 queries.py 的 COLUMNS，不是 STATUS.md —— 文件會落後，程式碼不會。 */
export type Job = {
  slug: string
  url: string
  job_name: string | null
  cust_name: string | null
  address: string | null
  appear_date: string | null
  salary_low: number | null
  salary_high: number | null
  salary: string | null
  status: 'judged' | 'list_rejected'
  rejected_by: string | null
  fit: boolean | null
  reason: string | null
  human_label: Label | null
  human_note: string | null
  starred: boolean
  starred_at: string | null
  first_seen_at: string | null
  judged_at: string | null
}

export type Label = 'yes' | 'no' | 'unsure'

export type Stats = {
  fit: number
  unfit: number
  filtered: number
  inbox: number
  unfit_open: number
  filtered_open: number
  starred: number
}

export type TabKey = 'inbox' | 'starred' | 'unfit' | 'filtered'

type View = { line: string; hint?: string }

export type Tab = {
  key: TabKey
  label: string
  /** 預設檢視：這個 verdict 裡我還沒標的。條件見 STATUS.md，三個軸是正交的 */
  params: Record<string, string>
  /** 「顯示已標註的」打開後的檢視。沒有這欄就是這個 tab 沒有切換 */
  all?: Record<string, string>
  /** tab 上的數字：預設檢視用 stat，切換後用 statAll */
  stat: keyof Stats
  statAll?: keyof Stats
  /** 預設檢視清空了（東西還在，切過去看得到） */
  cleared?: View
  /** 連已標註的都沒有 */
  empty: View
}

export const TABS: Tab[] = [
  {
    key: 'inbox',
    label: '收件匣',
    params: { verdict: 'fit', labeled: 'false' },
    all: { verdict: 'fit' },
    stat: 'inbox',
    statAll: 'fit',
    cleared: { line: '收件匣清空了。' },
    empty: { line: '還沒有 LLM 判為適合的職缺。' },
  },
  {
    key: 'starred',
    label: '收藏',
    // sort=starred 不能省，預設排序是 first_seen_at
    params: { starred: 'true', sort: 'starred' },
    stat: 'starred',
    empty: {
      line: '還沒有收藏。',
      hint: '標 Y（或在還沒標的職缺上按 ☆）會收藏到這裡，投完再取消。',
    },
  },
  {
    key: 'unfit',
    label: '不適合',
    params: { verdict: 'unfit', labeled: 'false' },
    all: { verdict: 'unfit' },
    stat: 'unfit_open',
    statAll: 'unfit',
    cleared: {
      line: '不適合的都掃過了。',
      hint: '這一頁是用來撿 LLM 漏掉的，標過的按「顯示已標註的」還在。',
    },
    empty: { line: '還沒有判為不適合的職缺。' },
  },
  {
    key: 'filtered',
    label: '規則刷掉',
    params: { verdict: 'filtered', labeled: 'false' },
    all: { verdict: 'filtered' },
    stat: 'filtered_open',
    statAll: 'filtered',
    cleared: {
      line: '規則刷掉的都掃過了。',
      hint: '這一頁是用來找被職稱或薪資規則誤殺的，標過的按「顯示已標註的」還在。',
    },
    empty: { line: '還沒有被規則刷掉的職缺。' },
  },
]
