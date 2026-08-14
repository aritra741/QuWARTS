-- Query 1: 1 (owner)
SELECT age, nba_team, name FROM owner WHERE nba_team != 'Cleveland Cavaliers';

-- Query 2: 2 (owner)
SELECT age, nba_team, name FROM owner WHERE nba_team != 'Golden State Warriors' AND age >= 66;

-- Query 3: 3 (owner)
SELECT age, name, nationality FROM owner WHERE age < 63 OR nationality != 'Israeli-American';

-- Query 4: 4 (owner)
SELECT own_year, nba_team, age FROM owner WHERE nba_team = 'Miami Heat' AND own_year != 2008 AND nationality != 'American  ' AND nationality != 'American  ';

-- Query 5: 5 (owner)
SELECT own_year, age, nationality FROM owner WHERE age <= 76 OR name = 'Joseph Chung-Hsin Tsai' OR own_year != 2012 OR own_year = 2017;

-- Query 6: 6 (owner)
SELECT nationality, age, name FROM owner WHERE (age >= 63 AND age = 63) OR (nba_team != 'Indiana Pacers' AND nba_team != 'New Orleans Pelicans');

