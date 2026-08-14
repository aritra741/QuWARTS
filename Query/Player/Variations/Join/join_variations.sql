-- Inspiration: Query 1 (join_queries.sql)
-- Variation: Selected different columns from player and team.
SELECT player.name, player.team, team.championship, team.founded_year FROM player JOIN team ON player.team = team.team_name;

-- Inspiration: Query 3 (join_queries.sql)
-- Variation: Focus on ownership and player awards.
SELECT team.team_name, team.ownership, player.name, player.mvp_awards, player.nba_championships FROM player JOIN team ON player.team = team.team_name;

-- Inspiration: Query 5 (join_queries.sql)
-- Variation: Team and city with area and gdp instead of population.
SELECT team.team_name, team.location, city.area, city.gdp, city.state_name FROM team JOIN city ON team.location = city.city_name;

-- Inspiration: Query 7 (join_queries.sql)
-- Variation: Owner with team name and own_year.
SELECT owner.name, owner.own_year, team.team_name, team.championship FROM team JOIN owner ON team.ownership = owner.name;

-- Inspiration: Query 1 (join_queries.sql multi_table)
-- Variation: Player, team, city with college and population.
SELECT player.name, player.college, team.team_name, city.city_name, city.population FROM player JOIN team ON player.team = team.team_name JOIN city ON team.location = city.city_name;

-- Inspiration: Query 5 (join_queries.sql multi_table)
-- Variation: Player, team, owner with draft and ownership.
SELECT player.name, player.draft_year, team.team_name, owner.name AS owner_name, owner.nationality FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name;

-- Inspiration: Query 9 (join_queries.sql)
-- Variation: Four-table join with different column selection.
SELECT player.name, team.team_name, city.city_name, owner.own_year FROM player JOIN team ON player.team = team.team_name JOIN owner ON team.ownership = owner.name JOIN city ON team.location = city.city_name;
