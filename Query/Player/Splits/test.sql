-- Query 1: test (agg_only) id=agg_only_gen_125
SELECT position, college, SUM(nba_championships) AS sum_nba_championships FROM player GROUP BY position, college;

-- Query 2: test (agg_only) id=agg_only_gen_104
SELECT nationality, team, SUM(mvp_awards) AS sum_mvp_awards FROM player GROUP BY nationality, team;

-- Query 3: test (agg_only) id=agg_only_gen_94
SELECT nationality, team, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player GROUP BY nationality, team;

-- Query 4: test (agg_only) id=agg_only_expanded_15
SELECT team, MAX(nba_championships) AS max_nba_championships FROM player GROUP BY team;

-- Query 5: test (agg_only) id=agg_only_gen_57
SELECT college, AVG(fiba_world_cup) AS avg_fiba_world_cup FROM player GROUP BY college;

-- Query 6: test (agg_filter) id=agg_filter_gen_186
SELECT team, AVG(age) AS avg_age FROM player WHERE (nationality != 'Nigerian-American') AND (team = 'Lokomotiv Kuban') GROUP BY team;

-- Query 7: test (agg_filter) id=mixed_queries_filter_agg_player_1
SELECT team, MIN(olympic_gold_medals) AS min_olympic_gold_medals FROM player WHERE draft_pick < 1 GROUP BY team;

-- Query 8: test (agg_filter) id=agg_filter_gen_85
SELECT position, COUNT(*) AS count_all FROM player WHERE nationality = 'French' GROUP BY position;

-- Query 9: test (agg_filter) id=agg_filter_gen_1
SELECT nationality, COUNT(*) AS count_all FROM player WHERE nationality = 'American' GROUP BY nationality;

-- Query 10: test (agg_filter) id=agg_filter_gen_196
SELECT team, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player WHERE (nationality = 'Nigerian-American' AND nationality != 'Croatian') OR (team != 'Bursaspor Basketbol') GROUP BY team;

-- Query 11: test (agg_join) id=agg_join_gen_28
SELECT player.college, COUNT(player.age) AS count_player_age FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.college;

-- Query 12: test (agg_join) id=agg_join_expanded_3
SELECT player.position, AVG(team.championship) AS avg_team_championship FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.position;

-- Query 13: test (agg_join) id=agg_join_gen_40
SELECT player.nationality, MIN(team.championship) AS min_team_championship FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.nationality;

-- Query 14: test (agg_join) id=agg_join_gen_4
SELECT player.position, MAX(player.mvp_awards) AS max_player_mvp_awards FROM player JOIN team ON player.team = team.team_name GROUP BY player.position;

-- Query 15: test (agg_join) id=agg_join_gen_17
SELECT team.location, SUM(player.mvp_awards) AS sum_player_mvp_awards FROM player JOIN team ON player.team = team.team_name GROUP BY team.location;

-- Query 16: test (agg_filter_join) id=agg_filter_join_gen_318
SELECT team.location, MIN(player.olympic_gold_medals) AS min_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE (city.gdp > 100) OR (player.nationality = 'American') GROUP BY team.location;

-- Query 17: test (agg_filter_join) id=agg_filter_join_gen_288
SELECT player.team, AVG(player.age) AS avg_player_age FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE (city.city_name = 'Los Angeles') OR (player.mvp_awards >= 1) GROUP BY player.team;

-- Query 18: test (agg_filter_join) id=agg_filter_join_gen_291
SELECT player.team, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE (city.city_name = 'San Antonio') OR (player.olympic_gold_medals = 0) GROUP BY player.team;

-- Query 19: test (agg_filter_join) id=agg_filter_join_gen_202
SELECT player.nationality, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE city.population < 2000000 GROUP BY player.nationality;

-- Query 20: test (agg_filter_join) id=agg_filter_join_gen_172
SELECT team.location, MAX(team.championship) AS max_team_championship FROM player JOIN team ON player.team = team.team_name WHERE city.city_name = 'Boston' GROUP BY team.location;

-- Query 21: test (agg_temporal) id=mixed_queries_filter_agg_join_11
SELECT player.nationality, SUM(player.mvp_awards) AS sum_player_mvp_awards FROM player JOIN team ON player.team = team.team_name WHERE player.team != 'Milwaukee Bucks' OR player.nba_championships > 2 OR team.founded_year != 1949 GROUP BY player.nationality;

-- Query 22: test (agg_temporal) id=agg_temporal_expanded_10
SELECT player.position, MAX(player.draft_pick) AS max_player_draft_pick FROM player WHERE player.birth_date = '1919/3/23' GROUP BY player.position;

-- Query 23: test (agg_temporal) id=agg_temporal_expanded_4
SELECT player.position, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name WHERE team.founded_year > 1946 GROUP BY player.position;

-- Query 24: test (agg_temporal) id=agg_temporal_gen_514
SELECT player.team, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name WHERE team.founded_year <= 1946 GROUP BY player.team;

-- Query 25: test (agg_temporal) id=agg_temporal_gen_507
SELECT player.nationality, AVG(player.age) AS avg_player_age FROM player JOIN team ON player.team = team.team_name WHERE team.founded_year > 1946 GROUP BY player.nationality;
