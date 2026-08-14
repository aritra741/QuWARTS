-- Inspiration: Query 1 (filter_queries_player.sql)
-- Variation: Filtered for positive FIBA world cup and selected different columns.
SELECT name, team, olympic_gold_medals FROM player WHERE fiba_world_cup > 0;

-- Inspiration: Query 4 (filter_queries_player.sql)
-- Variation: Filtered by different team (Lakers) and included position.
SELECT name, team, position, birth_date FROM player WHERE team = 'Los Angeles Lakers';

-- Inspiration: Query 7 (filter_queries_player.sql)
-- Variation: Swapped comparison for draft_year and fiba_world_cup.
SELECT name, draft_year, nationality FROM player WHERE draft_year >= 2018 AND fiba_world_cup <= 0;

-- Inspiration: Query 1 (filter_queries_team.sql)
-- Variation: Filtered by non-empty ownership and included championship.
SELECT team_name, ownership, championship, founded_year FROM team WHERE ownership != '  ';

-- Inspiration: Query 2 (filter_queries_team.sql)
-- Variation: Filtered for teams founded after 2000.
SELECT team_name, location, founded_year FROM team WHERE founded_year >= 2000;

-- Inspiration: Query 3 (filter_queries_team.sql)
-- Variation: Different ownership and founded_year thresholds.
SELECT team_name, ownership, location FROM team WHERE ownership != 'James L. Dolan' AND founded_year < 1970;

-- Inspiration: Query 1 (filter_queries_owner.sql)
-- Variation: Filtered by Golden State Warriors and added own_year.
SELECT name, nba_team, age, own_year FROM owner WHERE nba_team = 'Golden State Warriors';

-- Inspiration: Query 2 (filter_queries_owner.sql)
-- Variation: Younger owners (age < 60) and different team exclusion.
SELECT name, nba_team, nationality FROM owner WHERE age < 60 AND nba_team != 'Boston Celtics';

-- Inspiration: Query 1 (filter_queries_city.sql)
-- Variation: Filtered by different area and included gdp.
SELECT city_name, area, gdp, state_name FROM city WHERE area > 500;

-- Inspiration: Query 2 (filter_queries_city.sql)
-- Variation: Filter by population range and area.
SELECT city_name, population, area FROM city WHERE population > 500000 AND area != 1314.80;

-- Inspiration: Query 13 (filter_queries_player.sql)
-- Variation: OR condition for MVP winners or specific birth year.
SELECT name, team, mvp_awards, draft_year FROM player WHERE mvp_awards >= 1 OR birth_date = '1984/8/23';

-- Inspiration: Query 31 (filter_queries_player.sql)
-- Variation: Complex AND filter for nationality and position.
SELECT name, team, nationality, position FROM player WHERE (nationality = 'American  ' AND position = 'Backcourt') OR (draft_pick >= 10 AND draft_pick <= 20);
