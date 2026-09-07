CREATE TABLE
    jobs (
        slug TEXT PRIMARY KEY,
        status TEXT NOT NULL CHECK (status IN ('list_rejected', 'judged')),
        rejected_by TEXT,
        raw_list JSONB NOT NULL,
        raw_detail JSONB, 
        fit BOOLEAN,
        reason TEXT,
        prompt_sha256 TEXT,
        profile_sha256 TEXT,
        model TEXT,
        human_label TEXT,
        human_note TEXT,
        starred BOOLEAN NOT NULL DEFAULT FALSE,
        starred_at TIMESTAMPTZ,
        first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now (),
        judged_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now (),
        CONSTRAINT judged_has_verdict CHECK (
            status <> 'judged'
            OR (
                fit IS NOT NULL
                AND prompt_sha256 IS NOT NULL
                AND profile_sha256 IS NOT NULL
                AND model IS NOT NULL
            )
        ),
        CONSTRAINT rejected_has_reason CHECK (
            status = 'judged'
            OR rejected_by IS NOT NULL
        ),
        CONSTRAINT list_rejected_has_no_detail CHECK (
            status <> 'list_rejected'
            OR raw_detail IS NULL
        ),
        CONSTRAINT human_label_vocabulary CHECK (
            human_label IN ('yes', 'no', 'unsure')
        )
    );

