/** 104 的「以上」哨兵值：salary_high = 9999999 代表沒有上限。 */
const OPEN_ENDED = 9_999_999;

/** 月薪／年薪的分界，跟 pipeline.py 的 _salary_reject() 用同一條 30 萬。 */
const ANNUAL_FROM = 300_000;

const num = (n: number) => String(Number(n.toFixed(1)));

/**
 * salary_low / salary_high 排成人看的字串。
 * API 兩種形式都給就是為了這個：原字串 salary 拿去當 hover，數字自己排。
 */
export function fmtSalary(low: number | null, high: number | null): string {
  const lo = low ?? 0;
  const hi = high ?? 0;
  if (!lo && !hi) return "面議";

  const annual = Math.max(lo, hi === OPEN_ENDED ? 0 : hi) >= ANNUAL_FROM;
  const one = (n: number) =>
    annual ? `${num(n / 10_000)}萬` : `${num(n / 1000)}k`;
  const pair = (a: number, b: number) =>
    annual ? `${num(a / 10_000)}–${num(b / 10_000)}萬` : `${one(a)}–${one(b)}`;

  if (!hi || hi >= OPEN_ENDED) return `${one(lo)}+`;
  if (!lo) return `至 ${one(hi)}`;
  if (lo === hi) return one(lo);
  return pair(lo, hi);
}

/** appear_date 是 "20260904"。 */
export function fmtDate(raw: string | null): string {
  if (!raw || raw.length !== 8) return raw ?? "";
  return `${raw.slice(4, 6)}/${raw.slice(6, 8)}`;
}

const CITY =
  /^(台北|臺北|新北|桃園|新竹|苗栗|台中|臺中|彰化|南投|雲林|嘉義|台南|臺南|高雄|屏東|宜蘭|花蓮|台東|臺東|基隆|澎湖|金門|連江)[縣市]/;

/**
 * 只留到行政區，路名不顯示（「台北市信義區」→「台北信義」）。
 * 目前 104 的 jobAddrNoDesc 本來就只到行政區，這裡是防禦性的。
 */
export function fmtAddress(raw: string | null): string {
  if (!raw) return "";
  const s = raw.trim();
  const city = s.match(CITY);
  const head = city ? city[1] : "";
  const tail = city ? s.slice(city[0].length) : s;
  const district = tail.match(/^.*?[區鄉鎮市]/);
  const area = (district ? district[0] : tail).replace(/[區鄉鎮]$/, "");
  return head + area || s;
}

/** salary_* 來自 pipeline.py 的 _salary_reject()；job_name_blocklist 只剩舊資料（職稱擋掉的現在不寫 DB）。 */
const REJECTED: Record<string, string> = {
  job_name_blocklist: "職稱在黑名單裡",
  salary_monthly: "月薪級距上限低於門檻",
  salary_annual: "年薪級距上限低於門檻",
};

export function fmtRejectedBy(raw: string | null): string {
  if (!raw) return "規則刷掉";
  return REJECTED[raw] ?? `規則刷掉：${raw}`;
}
