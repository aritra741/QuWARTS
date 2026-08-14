-- ============================================================
-- Query-Awareness Trend Queries (Player Dataset)
-- All JOIN-only queries to isolate the workload-alignment signal.
-- Q1 (most workload-similar) → Q10 (most workload-dissimilar)
-- ============================================================

-- ── TIER 1: Near-identical to training binary joins (player ⟕ team) ──────────
-- These are almost verbatim from the training join workload.
-- Same tables, same join key, same kinds of projected columns.

-- Q1: Binary join (player ⟕ team), unfiltered — mirrors training Query 2/4
-- [Tables: player, team] [Ops: SELECT + JOIN]
SELECT player.name, player.nationality, player.age, team.team_name, team.location
FROM player
JOIN team ON player.team = team.team_name;

-- Q2: Binary join (player ⟕ team) with a familiar filter — mirrors training style
-- [Tables: player, team] [Ops: SELECT + JOIN + WHERE]
SELECT player.name, player.position, team.team_name, team.founded_year
FROM player
JOIN team ON player.team = team.team_name
WHERE player.age > 25;

-- ── TIER 2: Binary join, slightly novel column selection ─────────────────────
-- Same join path seen in training, but columns that were less frequently co-projected.

-- Q3: Binary join with less-common player attributes (draft_pick, college)
-- [Tables: player, team] [Ops: SELECT + JOIN + WHERE]
SELECT player.name, player.draft_pick, player.college, team.team_name
FROM player
JOIN team ON player.team = team.team_name
WHERE player.draft_pick >= 0;

-- Q4: Binary join (team ⟕ city) — seen in training but different column mix
-- [Tables: team, city] [Ops: SELECT + JOIN]
SELECT team.team_name, team.location, city.city_name, city.state_name
FROM team
JOIN city ON team.location = city.city_name;

-- ── TIER 3: 3-table join (player ⟕ team ⟕ city) — seen in training ──────────
-- The full 3-hop path appeared in training, but the specific column combinations differ.

-- Q5: 3-table join, unfiltered — similar to training multi_table_join Q1-Q4
-- [Tables: player, team, city] [Ops: SELECT + JOIN(3)]
SELECT player.name, team.team_name, city.city_name, city.state_name
FROM player
JOIN team ON player.team = team.team_name
JOIN city ON team.location = city.city_name;

-- Q6: 3-table join with age filter — same path, novel predicate
-- [Tables: player, team, city] [Ops: SELECT + JOIN(3) + WHERE]
SELECT player.name, player.position, city.city_name, city.population
FROM player
JOIN team ON player.team = team.team_name
JOIN city ON team.location = city.city_name
WHERE player.age < 35;

-- ── TIER 4: 3-table join with rarely-seen attributes / tighter filters ───────
-- Same join skeleton, but columns (gdp, birth_date, area) that were seldom
-- projected in training queries.

-- Q7: 3-table join projecting city.gdp and player.college — rarely co-selected
-- [Tables: player, team, city] [Ops: SELECT + JOIN(3) + WHERE]
SELECT player.name, player.college, team.team_name, city.gdp
FROM player
JOIN team ON player.team = team.team_name
JOIN city ON team.location = city.city_name
WHERE player.draft_pick > 0;

-- Q8: 3-table join projecting player.birth_date and city.area — almost never in training
-- [Tables: player, team, city] [Ops: SELECT + JOIN(3) + WHERE]
SELECT player.name, player.birth_date, team.team_name, city.area
FROM player
JOIN team ON player.team = team.team_name
JOIN city ON team.location = city.city_name
WHERE city.area > 100;

-- ── TIER 5: Reverse anchor (city → team → player) — never in training ───────
-- Training always anchored at player and traversed player→team→city.
-- These reverse the direction: city is the FROM table.

-- Q9: Reverse traversal with filter — city as anchor
-- [Tables: city, team, player] [Ops: SELECT + JOIN(3) + WHERE]
SELECT city.city_name, city.state_name, team.team_name, player.name
FROM city
JOIN team ON city.city_name = team.location
JOIN player ON player.team = team.team_name
WHERE player.age < 40;

-- Q10: Reverse traversal with novel column set — furthest from any training query
-- [Tables: city, team, player] [Ops: SELECT + JOIN(3) + WHERE]
SELECT city.city_name, city.state_name, team.team_name, player.name, player.college
FROM city
JOIN team ON city.city_name = team.location
JOIN player ON player.team = team.team_name
WHERE player.age > 20;
