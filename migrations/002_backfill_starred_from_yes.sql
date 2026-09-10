-- 收藏跟著標註走之後（queries.py 的 LABEL），把之前標了 yes 卻沒收藏的補上。
-- 只動資料、不動 schema，所以 find_jobs.sql 不用改。
--
-- starred_at 拿 updated_at 近似標註當下的時間：之後改標或收藏都會動到它，
-- 但這些 row 在這之前本來就只有標註會寫，差不到哪去。

UPDATE jobs SET
    starred    = TRUE,
    starred_at = updated_at
WHERE human_label = 'yes' AND NOT starred;
