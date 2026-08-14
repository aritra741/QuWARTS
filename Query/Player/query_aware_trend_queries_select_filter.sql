-- ============================================================
-- Query-Awareness Trend Queries (Player Dataset)
-- SELECT/FILTER only (no JOIN) for Map&Make fair baseline
-- Q1 (more workload-similar) -> Q10 (more diverse attributes)
-- ============================================================

-- Q1: Simple projection over player
SELECT player.name, player.nationality, player.age
FROM player;

-- Q2: Player projection with numeric filter
SELECT player.name, player.position, player.team
FROM player
WHERE player.age > 25;

-- Q3: Player projection with draft filter
SELECT player.name, player.draft_pick, player.college
FROM player
WHERE player.draft_pick >= 0;

-- Q4: Simple projection over team
SELECT team.team_name, team.location, team.founded_year
FROM team;

-- Q5: Team projection with filter
SELECT team.team_name, team.ownership, team.championship
FROM team
WHERE team.championship > 0;

-- Q6: Simple projection over city
SELECT city.city_name, city.state_name, city.population
FROM city;

-- Q7: City projection with area filter
SELECT city.city_name, city.area, city.gdp
FROM city
WHERE city.area > 100;

-- Q8: Simple projection over owner
SELECT owner.name, owner.nba_team, owner.own_year
FROM owner;

-- Q9: Owner projection with numeric filter
SELECT owner.name, owner.age, owner.nationality
FROM owner
WHERE owner.age > 50;

-- Q10: Broader player projection with filter
SELECT player.name, player.birth_date, player.team, player.position
FROM player
WHERE player.age < 35;
