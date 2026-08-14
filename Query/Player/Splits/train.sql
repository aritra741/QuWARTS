-- Query 1: train (agg_only) id=agg_only_expanded_20
SELECT college, MAX(nba_championships) AS max_nba_championships FROM player GROUP BY college;

-- Query 2: train (agg_only) id=agg_only_gen_113
SELECT team, college, MIN(mvp_awards) AS min_mvp_awards FROM player GROUP BY team, college;

-- Query 3: train (agg_only) id=agg_only_gen_138
SELECT nationality, college, COUNT(mvp_awards) AS count_mvp_awards FROM player GROUP BY nationality, college;

-- Query 4: train (agg_only) id=agg_only_gen_3
SELECT position, COUNT(mvp_awards) AS count_mvp_awards FROM player GROUP BY position;

-- Query 5: train (agg_only) id=agg_only_gen_105
SELECT nationality, team, MAX(fiba_world_cup) AS max_fiba_world_cup FROM player GROUP BY nationality, team;

-- Query 6: train (agg_only) id=agg_only_gen_47
SELECT college, COUNT(age) AS count_age FROM player GROUP BY college;

-- Query 7: train (agg_only) id=agg_only_gen_109
SELECT team, college, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player GROUP BY team, college;

-- Query 8: train (agg_only) id=agg_only_gen_50
SELECT college, SUM(nba_championships) AS sum_nba_championships FROM player GROUP BY college;

-- Query 9: train (agg_only) id=agg_only_gen_12
SELECT position, AVG(fiba_world_cup) AS avg_fiba_world_cup FROM player GROUP BY position;

-- Query 10: train (agg_only) id=agg_queries_6
SELECT nationality, MIN(age) AS min_age FROM player GROUP BY nationality;

-- Query 11: train (agg_only) id=agg_only_gen_73
SELECT position, nationality, MIN(draft_pick) AS min_draft_pick FROM player GROUP BY position, nationality;

-- Query 12: train (agg_only) id=agg_only_gen_86
SELECT position, team, MAX(age) AS max_age FROM player GROUP BY position, team;

-- Query 13: train (agg_only) id=agg_only_gen_54
SELECT college, MIN(olympic_gold_medals) AS min_olympic_gold_medals FROM player GROUP BY college;

-- Query 14: train (agg_only) id=agg_only_gen_33
SELECT team, COUNT(mvp_awards) AS count_mvp_awards FROM player GROUP BY team;

-- Query 15: train (agg_only) id=agg_only_expanded_16
SELECT college, COUNT(*) AS count_all FROM player GROUP BY college;

-- Query 16: train (agg_only) id=agg_only_gen_97
SELECT nationality, team, AVG(draft_pick) AS avg_draft_pick FROM player GROUP BY nationality, team;

-- Query 17: train (agg_only) id=agg_only_expanded_18
SELECT college, AVG(age) AS avg_age FROM player GROUP BY college;

-- Query 18: train (agg_only) id=agg_only_gen_141
SELECT nationality, college, AVG(age) AS avg_age FROM player GROUP BY nationality, college;

-- Query 19: train (agg_only) id=agg_only_gen_98
SELECT nationality, team, MIN(mvp_awards) AS min_mvp_awards FROM player GROUP BY nationality, team;

-- Query 20: train (agg_only) id=agg_only_gen_17
SELECT nationality, COUNT(age) AS count_age FROM player GROUP BY nationality;

-- Query 21: train (agg_filter) id=agg_filter_expanded_13
SELECT position, MAX(nba_championships) AS max_nba_championships FROM player WHERE nationality = 'American-Venezuelan' GROUP BY position;

-- Query 22: train (agg_filter) id=agg_filter_gen_84
SELECT position, COUNT(*) AS count_all FROM player WHERE (nationality != 'American' AND nationality = 'Canadian') OR (team = 'Cedevita Olimpija') GROUP BY position;

-- Query 23: train (agg_filter) id=agg_filter_gen_129
SELECT position, MIN(mvp_awards) AS min_mvp_awards FROM player WHERE nationality = 'American-born naturalized Azerbaijani' GROUP BY position;

-- Query 24: train (agg_filter) id=agg_filter_gen_168
SELECT team, COUNT(*) AS count_all FROM player WHERE (nationality != 'American-Venezuelan' AND nationality = 'Croatian') OR (team = 'Bursaspor Basketbol') GROUP BY team;

-- Query 25: train (agg_filter) id=agg_filter_gen_50
SELECT nationality, MIN(mvp_awards) AS min_mvp_awards FROM player WHERE (nationality != 'Serbian') AND (nationality = 'Dutch') GROUP BY nationality;

-- Query 26: train (agg_filter) id=agg_filter_gen_53
SELECT nationality, MIN(mvp_awards) AS min_mvp_awards FROM player WHERE nationality = 'American' GROUP BY nationality;

-- Query 27: train (agg_filter) id=agg_filter_gen_120
SELECT position, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player WHERE (nationality = 'American-born naturalized Azerbaijani' AND nationality != 'Greek-American') OR (team != 'Rochester Royals') GROUP BY position;

-- Query 28: train (agg_filter) id=agg_filter_gen_33
SELECT nationality, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player WHERE nationality = 'Serbian' GROUP BY nationality;

-- Query 29: train (agg_filter) id=mixed_queries_filter_agg_5
SELECT nationality, AVG(fiba_world_cup) AS avg_fiba_world_cup FROM player WHERE team = 'New York Knicks  ' OR nba_championships <= 0 OR fiba_world_cup < 0 GROUP BY nationality;

-- Query 30: train (agg_filter) id=agg_filter_gen_230
SELECT team, MAX(nba_championships) AS max_nba_championships FROM player WHERE (nationality != 'Dutch') AND (team = 'Los Angeles Lakers') GROUP BY team;

-- Query 31: train (agg_filter) id=agg_filter_gen_190
SELECT team, AVG(age) AS avg_age FROM player WHERE (nationality = 'Dutch') AND (team != 'Lokomotiv Kuban') GROUP BY team;

-- Query 32: train (agg_filter) id=agg_filter_gen_194
SELECT team, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player WHERE (nationality = 'Nigerian-American') AND (nationality != 'Croatian') GROUP BY team;

-- Query 33: train (agg_filter) id=agg_filter_gen_165
SELECT team, COUNT(*) AS count_all FROM player WHERE nationality != 'American-Venezuelan' GROUP BY team;

-- Query 34: train (agg_filter) id=agg_filter_gen_3
SELECT nationality, COUNT(*) AS count_all FROM player WHERE (nationality = 'American') OR (nationality != 'American-Venezuelan') GROUP BY nationality;

-- Query 35: train (agg_filter) id=agg_filter_expanded_5
SELECT nationality, MAX(nba_championships) AS max_nba_championships FROM player WHERE nationality != 'American' GROUP BY nationality;

-- Query 36: train (agg_filter) id=agg_filter_gen_115
SELECT position, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player WHERE (nationality != 'French') OR (nationality = 'Greek-American') GROUP BY position;

-- Query 37: train (agg_filter) id=agg_filter_gen_119
SELECT position, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player WHERE (nationality = 'American-born naturalized Azerbaijani') OR (nationality != 'Greek-American') GROUP BY position;

-- Query 38: train (agg_filter) id=agg_filter_gen_152
SELECT position, MAX(nba_championships) AS max_nba_championships FROM player WHERE (nationality = 'American-Venezuelan' AND nationality != 'Slovenian') OR (team != 'Orlando Magic') GROUP BY position;

-- Query 39: train (agg_filter) id=agg_filter_gen_200
SELECT team, SUM(olympic_gold_medals) AS sum_olympic_gold_medals FROM player WHERE (nationality != 'Nigerian-American' AND team = 'Lokomotiv Kuban') OR (team = 'Saski Baskonia') GROUP BY team;

-- Query 40: train (agg_filter) id=agg_filter_gen_56
SELECT nationality, MIN(mvp_awards) AS min_mvp_awards FROM player WHERE (nationality = 'American' AND nationality != 'Dutch') OR (team != 'Los Angeles Lakers') GROUP BY nationality;

-- Query 41: train (agg_join) id=agg_join_gen_7
SELECT team.location, MIN(team.championship) AS min_team_championship FROM player JOIN team ON player.team = team.team_name GROUP BY team.location;

-- Query 42: train (agg_join) id=agg_join_gen_36
SELECT player.team, MAX(player.olympic_gold_medals) AS max_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.team;

-- Query 43: train (agg_join) id=agg_join_gen_15
SELECT player.nationality, AVG(player.mvp_awards) AS avg_player_mvp_awards FROM player JOIN team ON player.team = team.team_name GROUP BY player.nationality;

-- Query 44: train (agg_join) id=agg_join_gen_16
SELECT player.team, MAX(player.olympic_gold_medals) AS max_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name GROUP BY player.team;

-- Query 45: train (agg_join) id=agg_join_gen_8
SELECT player.college, COUNT(player.age) AS count_player_age FROM player JOIN team ON player.team = team.team_name GROUP BY player.college;

-- Query 46: train (agg_join) id=mixed_queries_agg_join_1
SELECT player.position, MIN(player.olympic_gold_medals) AS min_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name GROUP BY player.position;

-- Query 47: train (agg_join) id=agg_join_gen_21
SELECT player.position, MIN(player.olympic_gold_medals) AS min_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.position;

-- Query 48: train (agg_join) id=agg_join_expanded_1
SELECT player.position, MAX(player.mvp_awards) AS max_player_mvp_awards FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.position;

-- Query 49: train (agg_join) id=agg_join_gen_3
SELECT player.team, AVG(player.age) AS avg_player_age FROM player JOIN team ON player.team = team.team_name GROUP BY player.team;

-- Query 50: train (agg_join) id=agg_join_gen_38
SELECT player.college, AVG(player.nba_championships) AS avg_player_nba_championships FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.college;

-- Query 51: train (agg_join) id=agg_join_expanded_5
SELECT player.position, COUNT(player.mvp_awards) AS count_player_mvp_awards FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.position;

-- Query 52: train (agg_join) id=agg_join_gen_9
SELECT player.position, AVG(team.championship) AS avg_team_championship FROM player JOIN team ON player.team = team.team_name GROUP BY player.position;

-- Query 53: train (agg_join) id=agg_join_gen_27
SELECT team.location, MIN(team.championship) AS min_team_championship FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY team.location;

-- Query 54: train (agg_join) id=agg_join_expanded_8
SELECT player.team, SUM(player.olympic_gold_medals) AS sum_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name GROUP BY player.team;

-- Query 55: train (agg_join) id=agg_join_gen_20
SELECT player.nationality, MIN(team.championship) AS min_team_championship FROM player JOIN team ON player.team = team.team_name GROUP BY player.nationality;

-- Query 56: train (agg_join) id=agg_join_gen_25
SELECT player.nationality, SUM(player.nba_championships) AS sum_player_nba_championships FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.nationality;

-- Query 57: train (agg_join) id=agg_join_gen_23
SELECT player.team, AVG(player.age) AS avg_player_age FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.team;

-- Query 58: train (agg_join) id=agg_join_gen_22
SELECT player.nationality, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.nationality;

-- Query 59: train (agg_join) id=agg_join_expanded_6
SELECT player.team, SUM(player.olympic_gold_medals) AS sum_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name GROUP BY player.team;

-- Query 60: train (agg_join) id=agg_join_expanded_2
SELECT player.nationality, SUM(player.nba_championships) AS sum_player_nba_championships FROM player JOIN team ON player.team = team.team_name GROUP BY player.nationality;

-- Query 61: train (agg_filter_join) id=agg_filter_join_expanded_12
SELECT player.team, MIN(player.olympic_gold_medals) AS min_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE city.city_name = 'Denver' GROUP BY player.team;

-- Query 62: train (agg_filter_join) id=agg_filter_join_gen_79
SELECT player.position, SUM(player.mvp_awards) AS sum_player_mvp_awards FROM player JOIN team ON player.team = team.team_name WHERE player.draft_pick <= 20 GROUP BY player.position;

-- Query 63: train (agg_filter_join) id=agg_filter_join_expanded_7
SELECT player.position, MAX(team.championship) AS max_team_championship FROM player JOIN team ON player.team = team.team_name WHERE team.championship > 0 GROUP BY player.position;

-- Query 64: train (agg_filter_join) id=agg_filter_join_gen_260
SELECT player.position, SUM(player.mvp_awards) AS sum_player_mvp_awards FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE (team.location = 'Brooklyn') AND (city.city_name = 'Boston') GROUP BY player.position;

-- Query 65: train (agg_filter_join) id=agg_filter_join_expanded_5
SELECT team.location, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name WHERE team.location = 'Boston' GROUP BY team.location;

-- Query 66: train (agg_filter_join) id=agg_filter_join_gen_29
SELECT player.nationality, SUM(player.mvp_awards) AS sum_player_mvp_awards FROM player JOIN team ON player.team = team.team_name WHERE (player.team = 'Los Angeles Lakers') AND (team.location = 'Atlanta') GROUP BY player.nationality;

-- Query 67: train (agg_filter_join) id=agg_filter_join_gen_20
SELECT player.nationality, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name WHERE (player.nationality = 'Nigerian-American') AND (player.team = 'Rochester Royals') GROUP BY player.nationality;

-- Query 68: train (agg_filter_join) id=agg_filter_join_gen_78
SELECT player.position, SUM(player.mvp_awards) AS sum_player_mvp_awards FROM player JOIN team ON player.team = team.team_name WHERE (player.age < 35) OR (team.championship > 0) GROUP BY player.position;

-- Query 69: train (agg_filter_join) id=agg_filter_join_expanded_16
SELECT team.location, AVG(player.age) AS avg_player_age FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE player.nationality = 'American' GROUP BY team.location;

-- Query 70: train (agg_filter_join) id=agg_filter_join_gen_298
SELECT player.team, SUM(player.mvp_awards) AS sum_player_mvp_awards FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE player.age > 28 GROUP BY player.team;

-- Query 71: train (agg_filter_join) id=agg_filter_join_gen_57
SELECT player.position, AVG(player.age) AS avg_player_age FROM player JOIN team ON player.team = team.team_name WHERE (team.location = 'Chicago') OR (city.city_name = 'Dallas') GROUP BY player.position;

-- Query 72: train (agg_filter_join) id=agg_filter_join_gen_94
SELECT player.team, MIN(player.olympic_gold_medals) AS min_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name WHERE city.population < 2000000 GROUP BY player.team;

-- Query 73: train (agg_filter_join) id=agg_filter_join_gen_199
SELECT player.nationality, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE player.mvp_awards >= 1 GROUP BY player.nationality;

-- Query 74: train (agg_filter_join) id=agg_filter_join_gen_184
SELECT player.nationality, MIN(player.olympic_gold_medals) AS min_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE player.age < 35 GROUP BY player.nationality;

-- Query 75: train (agg_filter_join) id=agg_filter_join_gen_189
SELECT player.nationality, MIN(player.olympic_gold_medals) AS min_player_olympic_gold_medals FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE (player.draft_pick <= 20) OR (city.gdp > 100) GROUP BY player.nationality;

-- Query 76: train (agg_filter_join) id=agg_filter_join_expanded_18
SELECT player.nationality, SUM(player.mvp_awards) AS sum_player_mvp_awards FROM player JOIN team ON player.team = team.team_name WHERE player.team = 'Los Angeles Lakers' GROUP BY player.nationality;

-- Query 77: train (agg_filter_join) id=agg_filter_join_gen_195
SELECT player.nationality, AVG(player.age) AS avg_player_age FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name WHERE (player.olympic_gold_medals = 0) OR (player.nba_championships != 2) GROUP BY player.nationality;

-- Query 78: train (agg_filter_join) id=agg_filter_join_gen_179
SELECT team.location, MAX(team.championship) AS max_team_championship FROM player JOIN team ON player.team = team.team_name WHERE (city.city_name = 'Los Angeles') AND (player.mvp_awards >= 1) GROUP BY team.location;

-- Query 79: train (agg_filter_join) id=agg_filter_join_expanded_11
SELECT player.team, SUM(player.mvp_awards) AS sum_player_mvp_awards FROM player JOIN team ON player.team = team.team_name WHERE (player.nationality = 'French') OR (player.team = 'Lokomotiv Kuban') GROUP BY player.team;

-- Query 80: train (agg_filter_join) id=mixed_queries_filter_agg_join_5
SELECT player.position, AVG(player.fiba_world_cup) AS avg_player_fiba_world_cup FROM player JOIN team ON player.team = team.team_name WHERE player.nba_championships < 0 OR player.age >= 47 OR player.nationality = 'Greek-American  ' GROUP BY player.position;

-- Query 81: train (agg_temporal) id=agg_temporal_expanded_8
SELECT player.team, MIN(player.draft_year) AS min_player_draft_year FROM player JOIN team ON player.team = team.team_name WHERE player.birth_date = '1919/3/23' GROUP BY player.team;

-- Query 82: train (agg_temporal) id=agg_temporal_gen_1
SELECT player.nationality, COUNT(*) AS count_all FROM player WHERE player.birth_date = '1919/3/23' GROUP BY player.nationality;

-- Query 83: train (agg_temporal) id=mixed_queries_filter_agg_player_4
SELECT position, MAX(mvp_awards) AS max_mvp_awards FROM player WHERE nba_championships = 0 AND draft_year > 2012 AND nba_championships != 2 GROUP BY position;

-- Query 84: train (agg_temporal) id=agg_temporal_gen_14
SELECT player.position, MIN(player.draft_year) AS min_player_draft_year FROM player JOIN team ON player.team = team.team_name WHERE player.birth_date = '1919/3/23' GROUP BY player.position;

-- Query 85: train (agg_temporal) id=agg_temporal_expanded_5
SELECT player.team, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name WHERE player.birth_date = '1919/3/23' GROUP BY player.team;

-- Query 86: train (agg_temporal) id=agg_temporal_gen_8
SELECT player.nationality, MAX(player.draft_pick) AS max_player_draft_pick FROM player JOIN team ON player.team = team.team_name WHERE player.birth_date = '1919/3/23' GROUP BY player.nationality;

-- Query 87: train (agg_temporal) id=agg_temporal_expanded_6
SELECT player.nationality, COUNT(*) AS count_all FROM player WHERE player.draft_year > 1985 GROUP BY player.nationality;

-- Query 88: train (agg_temporal) id=agg_temporal_expanded_2
SELECT player.nationality, AVG(player.age) AS avg_player_age FROM player WHERE player.draft_year > 1985 GROUP BY player.nationality;

-- Query 89: train (agg_temporal) id=agg_temporal_gen_589
SELECT player.draft_year, COUNT(*) AS count_all FROM player WHERE player.birth_date >= '1919/3/23' GROUP BY player.draft_year;

-- Query 90: train (agg_temporal) id=mixed_queries_filter_agg_4
SELECT nationality, MAX(mvp_awards) AS max_mvp_awards FROM player WHERE draft_year > 2012 OR nba_championships > 0 GROUP BY nationality;

-- Query 91: train (agg_temporal) id=agg_temporal_gen_513
SELECT player.team, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name WHERE team.founded_year > 1946 GROUP BY player.team;

-- Query 92: train (agg_temporal) id=agg_temporal_gen_510
SELECT player.position, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name WHERE team.founded_year <= 1946 GROUP BY player.position;

-- Query 93: train (agg_temporal) id=agg_temporal_gen_9
SELECT player.position, COUNT(*) AS count_all FROM player WHERE player.birth_date = '1919/3/23' GROUP BY player.position;

-- Query 94: train (agg_temporal) id=agg_temporal_expanded_7
SELECT player.position, COUNT(*) AS count_all FROM player JOIN team ON player.team = team.team_name WHERE player.birth_date = '1919/3/23' GROUP BY player.position;

-- Query 95: train (agg_temporal) id=agg_temporal_gen_515
SELECT player.team, AVG(player.age) AS avg_player_age FROM player JOIN team ON player.team = team.team_name WHERE team.founded_year > 1946 GROUP BY player.team;

-- Query 96: train (agg_temporal) id=agg_temporal_gen_13
SELECT player.position, MIN(player.draft_year) AS min_player_draft_year FROM player WHERE player.birth_date = '1919/3/23' GROUP BY player.position;

-- Query 97: train (agg_temporal) id=agg_temporal_gen_375
SELECT player.position, AVG(player.age) AS avg_player_age FROM player WHERE player.draft_year = 1985 GROUP BY player.position;

-- Query 98: train (agg_temporal) id=agg_temporal_gen_371
SELECT player.position, COUNT(*) AS count_all FROM player WHERE player.draft_year < 1985 GROUP BY player.position;

-- Query 99: train (agg_temporal) id=agg_temporal_gen_7
SELECT player.nationality, MAX(player.draft_pick) AS max_player_draft_pick FROM player WHERE player.birth_date = '1919/3/23' GROUP BY player.nationality;

-- Query 100: train (agg_temporal) id=agg_temporal_gen_369
SELECT player.nationality, MIN(player.draft_year) AS min_player_draft_year FROM player WHERE player.draft_year = 1985 GROUP BY player.nationality;
