import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import JobRow from './JobRow'
import { PAGE, getStats, listJobs, setLabel, setStar } from './api'
import { TABS, type Job, type Label, type Stats, type TabKey } from './types'

/**
 * 「一致」= human_label 跟 LLM 的 fit 同向。不一致才要一句話。
 * unsure 一律當作不一致；filtered 那批 fit 是 NULL，標 yes 本身就是分歧。
 */
function divergent(job: Job, label: Label): boolean {
  if (label === 'unsure') return true
  if (job.fit === null) return label === 'yes'
  return job.fit !== (label === 'yes')
}

type Pending = { slug: string; label: Label }

export default function App() {
  const [tabKey, setTabKey] = useState<TabKey>('inbox')
  const [jobs, setJobs] = useState<Job[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [writeError, setWriteError] = useState<string | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  // 收件匣預設只看沒標的；打開就看整個 fit 堆（含已標的）
  const [showLabeled, setShowLabeled] = useState(false)

  const tab = TABS.find((t) => t.key === tabKey)!
  // 給非同步的 callback 看現在停在哪個 tab（閉包裡的 tabKey 是舊的）
  const tabRef = useRef(tabKey)
  tabRef.current = tabKey

  // 三個 verdict tab 都是「這個 verdict 裡我還沒標的」，切換才把已標註的一起帶出來。
  // 少了這個切換，標了 yes 又沒收藏的職缺四個條件都不符合，會永遠消失。
  const showAll = tab.all !== undefined && showLabeled
  const params = useMemo(
    () => (showAll && tab.all ? tab.all : tab.params),
    [showAll, tab],
  )
  const total = (showAll && tab.statAll ? stats?.[tab.statAll] : stats?.[tab.stat]) ?? null

  const refreshStats = useCallback(() => {
    getStats()
      .then(setStats)
      .catch(() => {})
  }, [])

  // 切 tab 就重抓 —— 這正好是已標註的 row 該消失的時機。
  // cancelled 是給連續切 tab 用的：慢的那個回來時不能蓋掉新的
  useEffect(() => {
    let cancelled = false
    /* oxlint-disable-next-line react/set-state-in-effect
       -- 抓列表本來就是「跟外部系統同步」，loading 只能在這裡開始 */
    setLoading(true)
    setError(null)
    setPending(null)
    setNote('')
    listJobs(params, 0)
      .then((rows) => {
        if (cancelled) return
        setJobs(rows)
        setHasMore(rows.length === PAGE)
      })
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [params, reloadKey])

  useEffect(() => {
    refreshStats()
  }, [refreshStats])

  // Esc 取消 pending，即使焦點不在輸入框上
  useEffect(() => {
    if (!pending) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') cancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pending])

  function cancel() {
    setPending(null)
    setNote('')
    setWriteError(null)
  }

  function loadMore() {
    const at = tabKey
    setLoadingMore(true)
    listJobs(params, jobs.length)
      .then((rows) => {
        if (at !== tabRef.current) return // 載到一半切走了，這頁不屬於現在這個 tab
        setJobs((prev) => [...prev, ...rows])
        setHasMore(rows.length === PAGE)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoadingMore(false))
  }

  /**
   * POST 回傳更新後的整列，直接換掉 state 裡的那一筆 —— 不重抓列表，
   * 一重抓收件匣那筆就沒了。stats 另外抓一次。
   */
  function replace(row: Job) {
    setJobs((prev) => prev.map((j) => (j.slug === row.slug ? row : j)))
    refreshStats()
  }

  async function write(slug: string, run: () => Promise<Job>) {
    setBusy(slug)
    setWriteError(null)
    try {
      replace(await run())
      return true
    } catch (e) {
      setWriteError((e as Error).message)
      return false
    } finally {
      setBusy(null)
    }
  }

  async function commit(job: Job, label: Label | null, text: string) {
    const ok = await write(job.slug, () => setLabel(job.slug, label, text))
    if (ok) cancel()
  }

  function onLabel(job: Job, label: Label) {
    const here = pending?.slug === job.slug
    // 再點一次已經標好的那顆 = 收回標註。點錯了要有路回頭，這是唯一的一條
    if (!here && job.human_label === label) {
      void commit(job, null, '')
      return
    }
    if (divergent(job, label)) {
      // 一律從空白開始：框裡是什麼就會存什麼，預填等於幫你把過期的理由再送一次
      if (!here) setNote('')
      setPending({ slug: job.slug, label })
      setWriteError(null)
      return
    }
    // 跟 LLM 一樣：直接生效，不打斷。理由由 LABEL 的 CASE 清成 NULL
    void commit(job, label, '')
  }

  /**
   * 還沒標的按 ☆ = 標 Y，走同一條路（分歧一樣要理由，收藏由 LABEL 帶上）。
   * 標過的才是單純的 toggle —— 投完取消收藏，Y 留著。
   */
  function onStar(job: Job) {
    if (job.human_label === null) onLabel(job, 'yes')
    else void write(job.slug, () => setStar(job.slug, !job.starred))
  }

  return (
    <div className="mx-auto min-h-screen max-w-[1080px] px-3 sm:px-5">
      <header className="sticky top-0 z-10 bg-white">
        <div className="flex items-baseline gap-3 pt-5 pb-3">
          <h1 className="text-[15px] font-semibold tracking-tight">find-jobs</h1>
          <p className="text-[12.5px] text-mute">
            {stats
              ? `LLM 判為適合 ${stats.fit} 筆，還沒看 ${stats.inbox} 筆`
              : ' '}
          </p>
        </div>

        <nav className="flex items-center gap-0.5 border-b border-line" aria-label="清單">
          {TABS.map((t) => {
            const active = t.key === tabKey
            // badge 跟著檢視走：切換打開時顯示總數，不然點進去會發現數字對不上
            const count = showLabeled && t.statAll ? t.statAll : t.stat
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setTabKey(t.key)}
                aria-current={active ? 'page' : undefined}
                className={`-mb-px flex items-center gap-1.5 border-b-2 px-2.5 pt-1.5 pb-2 text-[14px] transition-colors sm:px-3 ${
                  active
                    ? 'border-accent font-semibold text-accent'
                    : 'border-transparent text-mute hover:text-ink'
                }`}
              >
                {t.label}
                <span
                  className={`text-[13px] tabular-nums ${
                    active ? 'text-accent/70' : 'text-[#b6b6b6]'
                  }`}
                >
                  {stats ? stats[count] : ''}
                </span>
              </button>
            )
          })}

          {tab.all && (
            <button
              type="button"
              onClick={() => setShowLabeled((v) => !v)}
              aria-pressed={showLabeled}
              className="ml-auto px-1 pt-1.5 pb-2 text-[12.5px] text-mute transition-colors hover:text-ink"
            >
              {showLabeled ? '只看還沒標的' : '顯示已標註的'}
            </button>
          )}
        </nav>
      </header>

      {writeError && (
        <p className="mt-3 border-l-2 border-accent bg-wash px-3 py-2 text-[13px] text-read">
          沒寫進去：{writeError}
        </p>
      )}

      <main>
        {loading ? (
          <Skeleton />
        ) : error ? (
          <Failed message={error} onRetry={() => setReloadKey((k) => k + 1)} />
        ) : jobs.length === 0 ? (
          <Empty
            view={showAll ? tab.empty : (tab.cleared ?? tab.empty)}
            stats={stats}
            cleared={!showAll && tab.cleared !== undefined && tabKey === 'inbox'}
          />
        ) : (
          <>
            <ul>
              {jobs.map((job) => (
                <JobRow
                  key={job.slug}
                  job={job}
                  pendingLabel={pending?.slug === job.slug ? pending.label : null}
                  note={note}
                  busy={busy === job.slug}
                  onNote={setNote}
                  onLabel={(label) => onLabel(job, label)}
                  onSubmit={() => pending && commit(job, pending.label, note)}
                  onCancel={cancel}
                  onStar={() => onStar(job)}
                />
              ))}
            </ul>

            <div className="py-6 text-center">
              {hasMore && (
                <button
                  type="button"
                  onClick={loadMore}
                  disabled={loadingMore}
                  className="rounded-[3px] border border-line px-4 py-1.5 text-[13.5px] text-read transition-colors hover:border-mute hover:text-ink disabled:opacity-50"
                >
                  {loadingMore ? '載入中' : '載入更多'}
                </button>
              )}
              <p className="mt-3 text-[12.5px] text-mute tabular-nums">
                顯示 {jobs.length}
                {total !== null && ` / ${total}`} 筆
              </p>
            </div>
          </>
        )}
      </main>
    </div>
  )
}

function Skeleton() {
  return (
    <ul aria-hidden="true">
      {Array.from({ length: 6 }, (_, i) => (
        <li key={i} className="animate-pulse border-b border-line px-3 pt-[13px] pb-[15px] sm:px-4">
          <div className="h-[14px] w-[34%] rounded-[2px] bg-[#ededed]" />
          <div className="mt-[10px] h-[12px] w-[58%] rounded-[2px] bg-[#f3f3f3]" />
        </li>
      ))}
    </ul>
  )
}

function Failed({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="px-3 py-16 sm:px-4">
      <p className="text-[14px] text-ink">讀不到資料。</p>
      <p className="mt-1 text-[13px] text-mute">{message}</p>
      <p className="mt-1 text-[13px] text-mute">
        確認 <code>uv run fastapi dev api.py</code> 還在 8000 上跑著。
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 rounded-[3px] border border-line px-3 py-1.5 text-[13.5px] text-read transition-colors hover:border-mute hover:text-ink"
      >
        重試
      </button>
    </div>
  )
}

function Empty({
  view,
  stats,
  cleared,
}: {
  view: { line: string; hint?: string }
  stats: Stats | null
  cleared: boolean
}) {
  // 收件匣清空是這個工具唯一的達成狀態，那就講下一步在哪
  const hint =
    cleared && stats && stats.starred > 0
      ? `收藏了 ${stats.starred} 筆，去投吧。`
      : view.hint
  return (
    <div className="px-3 py-16 sm:px-4">
      <p className="text-[14px] text-ink">{view.line}</p>
      {hint && <p className="mt-1.5 max-w-[52ch] text-[13px] leading-[1.6] text-mute">{hint}</p>}
    </div>
  )
}
