-- Inspiration: Query 1 (mixed_queries_filter_agg_owner.sql)
-- Variation: MAX age instead of MIN, filtered by different team.
SELECT nationality, MAX(age) AS max_age FROM owner WHERE nba_team != 'Golden State Warriors' GROUP BY nationality;

-- Inspiration: Query 2 (mixed_queries_filter_agg_owner.sql)
-- Variation: AVG age instead of SUM, different filter values.
SELECT nationality, AVG(age) AS avg_age FROM owner WHERE age < 70 AND nba_team != 'Houston Rockets' GROUP BY nationality;

-- Inspiration: Query 1 (mixed_queries_filter_agg_player.sql)
-- Variation: MAX olympic_gold_medals grouped by team, filtered by draft_pick.
SELECT team, MAX(olympic_gold_medals) AS max_olympic_gold_medals FROM player WHERE draft_pick >= 1 GROUP BY team;

-- Inspiration: Query 3 (mixed_queries_filter_agg_player.sql)
-- Variation: Count by team instead of nationality, different OR condition.
SELECT team, COUNT(*) AS count_all FROM player WHERE name = 'LeBron James' OR nba_championships >= 1 GROUP BY team;

-- Inspiration: Query 1 (mixed_queries_filter_join.sql)
-- Variation: Filter by nba_championships and select different columns.
SELECT player.name, team.team_name, player.nba_championships, team.championship FROM player JOIN team ON player.team = team.team_name WHERE player.nba_championships > 0;

-- Inspiration: Query 2 (mixed_queries_filter_join.sql)
-- Variation: Filter by player position and city population threshold.
SELECT player.name, player.position, city.city_name, city.population FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name WHERE player.position = 'Backcourt' AND city.population > 1000000;

-- Inspiration: Query 6 (mixed_queries_filter_agg.sql)
-- Variation: MIN mvp_awards by position with different composite filter.
SELECT position, MIN(mvp_awards) AS min_mvp_awards FROM player WHERE (fiba_world_cup >= 0 AND mvp_awards >= 0) OR (age >= 25 AND draft_year <= 2015) GROUP BY position;
