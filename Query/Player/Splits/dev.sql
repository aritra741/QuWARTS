-- Query 1: dev (agg_only) id=agg_only_gen_150
SELECT nationality, college, MAX(fiba_world_cup) AS max_fiba_world_cup FROM player GROUP BY nationality, college;

-- Query 2: dev (agg_only) id=agg_only_gen_60
SELECT college, MAX(fiba_world_cup) AS max_fiba_world_cup FROM player GROUP BY college;

-- Query 3: dev (agg_only) id=agg_only_expanded_13
SELECT team, AVG(age) AS avg_age FROM player GROUP BY team;

-- Query 4: dev (agg_only) id=agg_only_expanded_17
SELECT college, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player GROUP BY college;

-- Query 5: dev (agg_only) id=agg_only_gen_58
SELECT college, MIN(draft_pick) AS min_draft_pick FROM player GROUP BY college;

-- Query 6: dev (agg_filter) id=agg_filter_gen_184
SELECT team, AVG(age) AS avg_age FROM player WHERE (nationality = 'Nigerian-American' AND nationality != 'Croatian') OR (team != 'Bursaspor Basketbol') GROUP BY team;

-- Query 7: dev (agg_filter) id=agg_filter_gen_229
SELECT team, MAX(nba_championships) AS max_nba_championships FROM player WHERE nationality != 'Dutch' GROUP BY team;

-- Query 8: dev (agg_filter) id=agg_filter_gen_103
SELECT position, AVG(age) AS avg_age FROM player WHERE (nationality != 'French') OR (nationality = 'Greek-American') GROUP BY position;

-- Query 9: dev (agg_filter) id=mixed_queries_filter_agg_6
SELECT position, MIN(fiba_world_cup) AS min_fiba_world_cup FROM player WHERE (fiba_world_cup < 0 AND mvp_awards <= 0) OR (age < 91 AND fiba_world_cup >= 0) GROUP BY position;

-- Query 10: dev (agg_filter) id=mixed_queries_filter_agg_player_6
SELECT team, MIN(fiba_world_cup) AS min_fiba_world_cup FROM player WHERE (fiba_world_cup > 0 AND mvp_awards <= 0) OR (age < 91 AND fiba_world_cup >= 0) GROUP BY team;

-- Query 11: dev (agg_join) id=agg_join_expanded_7
SELECT player.position, COUNT(player.mvp_awards) AS count_player_mvp_awards FROM player JOIN team ON player.team = team.team_name GROUP BY player.position;

-- Query 12: dev (agg_join) id=agg_join_gen_10
SELECT player.nationality, MAX(player.age) AS max_player_age FROM player JOIN team ON player.team = team.team_name GROUP BY player.nationality;

-- Query 13: dev (agg_join) id=agg_join_gen_33
SELECT player.college, MIN(player.draft_pick) AS min_player_draft_pick FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.college;

-- Query 14: dev (agg_join) id=agg_join_gen_13
SELECT player.college, MIN(player.draft_pick) AS min_player_draft_pick FROM player JOIN team ON player.team = team.team_name GROUP BY player.college;

-- Query 15: dev (agg_join) id=agg_join_gen_26
SELECT team.location, AVG(player.fiba_world_cup) AS avg_player_fiba_world_cup FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY team.location;

-- Query 16: dev (agg_filter_join) id=agg_filter_join_gen_334
SELECT team.location, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE player.nationality = 'French' GROUP BY team.location;

-- Query 17: dev (agg_filter_join) id=agg_filter_join_gen_22
SELECT player.nationality, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name WHERE player.team = 'Lokomotiv Kuban' GROUP BY player.nationality;

-- Query 18: dev (agg_filter_join) id=agg_filter_join_gen_12
SELECT player.nationality, AVG(player.age) AS avg_player_age FROM player JOIN team ON player.team = team.team_name WHERE (player.nationality = 'French') OR (player.team = 'Lokomotiv Kuban') GROUP BY player.nationality;

-- Query 19: dev (agg_filter_join) id=agg_filter_join_gen_135
SELECT player.team, MAX(team.championship) AS max_team_championship FROM player JOIN team ON player.team = team.team_name WHERE (player.team = 'Cedevita Olimpija') OR (team.location = 'Boston') GROUP BY player.team;

-- Query 20: dev (agg_filter_join) id=agg_filter_join_gen_163
SELECT team.location, SUM(player.mvp_awards) AS sum_player_mvp_awards FROM player JOIN team ON player.team = team.team_name WHERE team.location = 'Chicago' GROUP BY team.location;

-- Query 21: dev (agg_temporal) id=agg_temporal_gen_367
SELECT player.nationality, MIN(player.draft_year) AS min_player_draft_year FROM player WHERE player.draft_year > 1985 GROUP BY player.nationality;

-- Query 22: dev (agg_temporal) id=agg_temporal_gen_17
SELECT player.team, COUNT(*) AS count_all FROM player WHERE player.birth_date = '1919/3/23' GROUP BY player.team;

-- Query 23: dev (agg_temporal) id=agg_temporal_gen_366
SELECT player.nationality, AVG(player.age) AS avg_player_age FROM player WHERE player.draft_year = 1985 GROUP BY player.nationality;

-- Query 24: dev (agg_temporal) id=agg_temporal_expanded_1
SELECT player.nationality, MIN(player.draft_year) AS min_player_draft_year FROM player JOIN team ON player.team = team.team_name WHERE player.birth_date = '1919/3/23' GROUP BY player.nationality;

-- Query 25: dev (agg_temporal) id=agg_temporal_gen_372
SELECT player.position, COUNT(*) AS count_all FROM player WHERE player.draft_year = 1985 GROUP BY player.position;
