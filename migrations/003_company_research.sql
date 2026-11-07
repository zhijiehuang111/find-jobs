-- 公司調查的報告（#13）。只加一張表，merge 前先在 VPS 跑。

CREATE TABLE
    company_research (
        company TEXT PRIMARY KEY,
        status TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed')),
        report JSONB,
        error TEXT,
        model TEXT,
        started_at TIMESTAMPTZ NOT NULL DEFAULT now (),
        finished_at TIMESTAMPTZ,
        CONSTRAINT done_has_report CHECK (
            status <> 'done'
            OR report IS NOT NULL
        )
    );
