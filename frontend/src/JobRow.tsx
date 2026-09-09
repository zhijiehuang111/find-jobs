import type { Job, Label } from './types'
import { fmtAddress, fmtDate, fmtRejectedBy, fmtSalary } from './format'

const LABELS: { value: Label; text: string; title: string }[] = [
  { value: 'yes', text: 'Y', title: '我適合這個職缺' },
  { value: 'no', text: 'N', title: '我不適合這個職缺' },
  { value: 'unsure', text: '?', title: '說不準' },
]

function Star({ filled }: { filled: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="15"
      height="15"
      aria-hidden="true"
      fill={filled ? 'var(--color-accent-lit)' : 'none'}
      stroke={filled ? 'var(--color-accent)' : 'currentColor'}
      strokeWidth="1.6"
      strokeLinejoin="round"
    >
      <path d="M12 3.6l2.6 5.3 5.8.85-4.2 4.1 1 5.75L12 16.9l-5.2 2.7 1-5.75-4.2-4.1 5.8-.85z" />
    </svg>
  )
}

type Props = {
  job: Job
  /** 這一列正在等 Enter 的那顆；null = 這一列沒有 pending */
  pendingLabel: Label | null
  note: string
  busy: boolean
  onNote: (value: string) => void
  onLabel: (label: Label) => void
  onSubmit: () => void
  onCancel: () => void
  onStar: () => void
}

export default function JobRow({
  job,
  pendingLabel,
  note,
  busy,
  onNote,
  onLabel,
  onSubmit,
  onCancel,
  onStar,
}: Props) {
  const pending = pendingLabel !== null
  // 已標註的列就地變淡（不抽掉，留在原位當天然 undo）；pending 不算已標註，不變淡
  const done = job.human_label !== null && !pending

  return (
    <li className="relative border-b border-line">
      {pending && (
        // 捲走了還找得回來是哪一列打到一半
        <span className="absolute inset-y-0 left-0 w-[2px] bg-accent" aria-hidden="true" />
      )}
      <div className="px-3 pt-[10px] pb-[11px] transition-colors hover:bg-wash sm:px-4">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-3">
          {/* 標題太長就換行，不 truncate —— 職稱是認出這筆是誰的唯一依據 */}
          <div className="min-w-0 flex-1 leading-[1.45]">
            <a
              href={job.url}
              target="_blank"
              rel="noreferrer"
              className={`text-[15px] font-semibold hover:underline ${
                done ? 'text-mute' : 'text-ink'
              }`}
            >
              {job.job_name ?? job.slug}
            </a>
            {job.cust_name && (
              <span className="text-[14px] text-mute"> · {job.cust_name}</span>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-3 text-[12.5px] text-mute">
            <span
              className="tabular-nums sm:w-[86px] sm:text-right"
              title={job.salary ?? undefined}
            >
              {fmtSalary(job.salary_low, job.salary_high)}
            </span>
            <span className="sm:w-[66px] sm:truncate">{fmtAddress(job.address)}</span>
            <span className="tabular-nums sm:w-[38px]">{fmtDate(job.appear_date)}</span>

            <button
              type="button"
              onClick={onStar}
              disabled={busy}
              aria-pressed={job.starred}
              title={job.starred ? '取消收藏' : '收藏'}
              className={`grid size-[30px] shrink-0 place-items-center sm:size-[26px] rounded-[3px] border border-transparent transition-colors hover:border-line hover:bg-white disabled:opacity-40 ${
                job.starred ? '' : 'text-[#b4b4b4] hover:text-mute'
              }`}
            >
              <Star filled={job.starred} />
            </button>

            <div className="flex shrink-0 items-center gap-1">
              {LABELS.map((l) => {
                const isPending = pendingLabel === l.value
                const isSet = !pending && job.human_label === l.value
                return (
                  <button
                    key={l.value}
                    type="button"
                    onClick={() => onLabel(l.value)}
                    disabled={busy}
                    title={l.title}
                    aria-pressed={isSet}
                    className={[
                      'h-[28px] min-w-[32px] rounded-[3px] border px-1.5 text-[12.5px] leading-none transition-colors disabled:opacity-40 sm:h-[24px] sm:min-w-[28px]',
                      isSet
                        ? // 已寫進 DB：填滿
                          'border-ink bg-ink font-medium text-white'
                        : isPending
                          ? // 選了但還沒 Enter：只有外框
                            'border-ink bg-white font-medium text-ink'
                          : 'border-transparent text-[#9b9b9b] hover:border-line hover:bg-white hover:text-ink',
                    ].join(' ')}
                  >
                    {l.text}
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        {/* reason 是每天唯一真的會讀的東西：完整顯示、不 truncate */}
        {job.reason ? (
          <p
            className={`mt-[3px] max-w-[72ch] text-[14px] leading-[1.65] ${
              done ? 'text-[#9c9c9c]' : 'text-read'
            }`}
          >
            {job.reason}
          </p>
        ) : (
          // list_rejected 沒有 reason；改放是哪條規則刷的 —— 那個 tab 就是拿來找誤殺的
          <p className="mt-[3px] text-[13px] leading-[1.65] text-mute">
            {fmtRejectedBy(job.rejected_by)}
          </p>
        )}

        {job.human_note && !pending && (
          <p className="mt-[5px] max-w-[72ch] border-l-2 border-line pl-2 text-[12.5px] leading-[1.6] text-mute">
            {job.human_note}
          </p>
        )}

        {pending && (
          <div className="mt-[7px] flex flex-wrap items-center gap-x-3 gap-y-1">
            <input
              autoFocus
              value={note}
              disabled={busy}
              onChange={(e) => onNote(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  onSubmit()
                } else if (e.key === 'Escape') {
                  e.preventDefault()
                  onCancel()
                }
              }}
              placeholder="一句話：為什麼？（可以留空）"
              className="min-w-0 flex-1 border-b border-line bg-transparent py-[3px] text-[13.5px] text-ink outline-none transition-colors placeholder:text-[#b8b8b8] focus:border-accent sm:max-w-[520px]"
            />
            <span className="shrink-0 text-[11.5px] text-mute">
              Enter 送出 · Esc 取消
            </span>
          </div>
        )}
      </div>
    </li>
  )
}
