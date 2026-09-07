-- human_label 從 BOOLEAN 改成跟考卷同一套詞彙（labels.tsv 的 yes / no / unsure）。
--
-- 另外兩個欄位：
--   human_note  我自己的理由。DB 的 reason 是 LLM 的，eval 要的是我的。
--   starred_at  收藏清單要照收藏時間排；updated_at 不能用，標 label 也會動到它。

ALTER TABLE jobs
    ALTER COLUMN human_label TYPE TEXT
        USING CASE WHEN human_label THEN 'yes' WHEN NOT human_label THEN 'no' END,
    ADD CONSTRAINT human_label_vocabulary CHECK (
        human_label IN ('yes', 'no', 'unsure')
    ),
    ADD COLUMN human_note TEXT,
    ADD COLUMN starred_at TIMESTAMPTZ;
