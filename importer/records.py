"""Pregame win/loss records, shared by all importers."""


def apply_pregame_records(conn, season) -> int:
    """Set home_record/away_record of every game in `season` to each team's
    regular-season record before that game.

    Only regular-season games count toward a record; postseason games show the
    team's final regular-season record. Teams are keyed by id, which is unique
    per sport, so all sports sharing a season label are handled in one pass.
    """

    def fmt(w: int, l: int, t: int) -> str:
        return f"{w}-{l}" if t == 0 else f"{w}-{l}-{t}"

    team_wlt: dict[int, tuple[int, int, int]] = {}
    updates: list[tuple[str, str, int]] = []

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, type, home_team_id, away_team_id, home_points, away_points "
            "FROM games "
            "WHERE season = %s "
            "AND game_date IS NOT NULL "
            "AND home_team_id IS NOT NULL "
            "AND away_team_id IS NOT NULL "
            "ORDER BY game_date ASC, id ASC",
            (str(season),),
        )
        rows = cur.fetchall()

    for game_id, game_type, home_id, away_id, home_points, away_points in rows:
        hw, hl, ht = team_wlt.get(home_id, (0, 0, 0))
        aw, al, at = team_wlt.get(away_id, (0, 0, 0))
        updates.append((fmt(hw, hl, ht), fmt(aw, al, at), game_id))

        if game_type != "regular" or home_points is None or away_points is None:
            continue
        # 0-0 marks a postponed/unplayed game, not a tie.
        if home_points == 0 and away_points == 0:
            continue

        if home_points > away_points:
            team_wlt[home_id] = (hw + 1, hl, ht)
            team_wlt[away_id] = (aw, al + 1, at)
        elif home_points < away_points:
            team_wlt[home_id] = (hw, hl + 1, ht)
            team_wlt[away_id] = (aw + 1, al, at)
        else:
            team_wlt[home_id] = (hw, hl, ht + 1)
            team_wlt[away_id] = (aw, al, at + 1)

    if not updates:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE games SET home_record = %s, away_record = %s WHERE id = %s",
            updates,
        )

    return len(updates)
