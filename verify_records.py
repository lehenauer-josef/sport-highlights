#!/usr/bin/env python3
import psycopg2
import os

conn = psycopg2.connect(
    host=os.getenv('PG_HOST', 'localhost'),
    port=int(os.getenv('PG_PORT', '5433')),
    database=os.getenv('PG_DATABASE', 'highlights'),
    user=os.getenv('PG_USER', 'highlights'),
    password=os.getenv('PG_PASSWORD', 'highlights'),
)

with conn.cursor() as cur:
    # Get week-1 and week-3 games to verify trends
    cur.execute("""
        SELECT g.id, g.week, g.game_date::date, 
               g.home_team_id, ht.name, g.home_record, g.home_points,
               g.away_team_id, at.name, g.away_record, g.away_points
        FROM games g
        JOIN teams ht ON g.home_team_id = ht.id
        JOIN teams at ON g.away_team_id = at.id
        WHERE g.season = 2026 AND g.week IN (1, 3)
        ORDER BY g.week, g.game_date
        LIMIT 2
    """)
    
    for row in cur.fetchall():
        game_id, week, game_date, home_id, home_name, home_rec, home_pts, away_id, away_name, away_rec, away_pts = row
        print(f"Week {week} ({game_date}): {home_name} ({home_rec}) {home_pts} vs {away_name} ({away_rec}) {away_pts}")

    # Check if week-1 games have 0-0 records
    print("\n--- Week 1 record check (should be 0-0) ---")
    cur.execute("""
        SELECT COUNT(*) 
        FROM games 
        WHERE season = 2026 AND week = 1 AND home_record = '0-0' AND away_record = '0-0'
    """)
    count = cur.fetchone()[0]
    print(f"Week-1 games with 0-0 records: {count}")

    # Check if week-3 games have non-zero records
    print("\n--- Week 3 record check (should be 1-0, 0-1, or 1-1 at minimum) ---")
    cur.execute("""
        SELECT COUNT(*) 
        FROM games 
        WHERE season = 2026 AND week = 3 AND home_record IS NOT NULL AND home_record != '0-0'
    """)
    count = cur.fetchone()[0]
    print(f"Week-3 games with non-zero home records: {count} (should be around 128)")

conn.close()
