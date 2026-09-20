import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import nflreadpy as nfl
import psycopg


DATABASE_URL = os.environ["DATABASE_URL"]

SEASONS = list(range(2019, 2027))


def value(row, *names):
    """Return the first available column value."""
    for name in names:
        if name in row:
            return row[name]
    return None


def clean(value):
    """Convert Polars nulls to Python None."""
    if value is None:
        return None
    try:
        if value != value:
            return None
    except Exception:
        pass
    return value


def game_datetime(gameday, gametime):
    if not gameday:
        return None

    if not gametime:
        return datetime.fromisoformat(
            str(gameday)
        ).replace(tzinfo=timezone.utc)

    try:
        local = datetime.fromisoformat(
            f"{gameday} {gametime}"
        ).replace(tzinfo=ZoneInfo("America/New_York"))

        return local.astimezone(timezone.utc)
    except Exception:
        return datetime.fromisoformat(
            str(gameday)
        ).replace(tzinfo=timezone.utc)


def main():
    print("Loading NFL data from nflverse...")
    print(f"Seasons: {SEASONS}")

    teams = nfl.load_teams()
    players = nfl.load_players()
    schedules = nfl.load_schedules(SEASONS)
    stats = nfl.load_player_stats(
        SEASONS,
        summary_level="week"
    )

    print(f"Teams loaded: {len(teams)}")
    print(f"Players loaded: {len(players)}")
    print(f"Games loaded: {len(schedules)}")
    print(f"Player stat rows loaded: {len(stats)}")

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:

            # ==================================================
            # TEAMS
            # ==================================================

            for row in teams.iter_rows(named=True):
                team_abbr = clean(value(row, "team_abbr"))

                if not team_abbr:
                    continue

                cur.execute(
                    """
                    INSERT INTO teams (
                        team_id,
                        team_name,
                        abbreviation,
                        conference,
                        division
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (team_id)
                    DO UPDATE SET
                        team_name = EXCLUDED.team_name,
                        abbreviation = EXCLUDED.abbreviation,
                        conference = EXCLUDED.conference,
                        division = EXCLUDED.division,
                        updated_at = now()
                    """,
                    (
                        team_abbr,
                        clean(value(row, "team_name")),
                        team_abbr,
                        clean(value(row, "team_conf")),
                        clean(value(row, "team_division")),
                    ),
                )

            print("Teams inserted.")

            # ==================================================
            # PLAYERS
            # ==================================================

            for row in players.iter_rows(named=True):
                player_id = clean(
                    value(row, "gsis_id", "player_id")
                )

                if not player_id:
                    continue

                cur.execute(
                    """
                    INSERT INTO players (
                        player_id,
                        player_name,
                        first_name,
                        last_name,
                        position,
                        status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (player_id)
                    DO UPDATE SET
                        player_name = EXCLUDED.player_name,
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        position = EXCLUDED.position,
                        updated_at = now()
                    """,
                    (
                        player_id,
                        clean(value(
                            row,
                            "display_name",
                            "player_display_name",
                            "full_name",
                            "name"
                        )) or "Unknown",
                        clean(value(row, "first_name")),
                        clean(value(row, "last_name")),
                        clean(value(row, "position")),
                        clean(value(row, "status")),
                    ),
                )

            print("Players inserted.")

            # ==================================================
            # GAMES
            # ==================================================

            for row in schedules.iter_rows(named=True):
                game_id = clean(value(row, "game_id"))

                if not game_id:
                    continue

                away = clean(value(row, "away_team"))
                home = clean(value(row, "home_team"))

                # Make sure teams referenced by games exist.
                for team in (away, home):
                    if team:
                        cur.execute(
                            """
                            INSERT INTO teams (
                                team_id,
                                team_name,
                                abbreviation
                            )
                            VALUES (%s, %s, %s)
                            ON CONFLICT (team_id)
                            DO NOTHING
                            """,
                            (team, team, team),
                        )

                game_type = clean(value(row, "game_type"))

                status = (
                    "final"
                    if clean(value(row, "result")) is not None
                    else "scheduled"
                )

                spread = clean(value(
                    row,
                    "spread_line",
                    "spread"
                ))

                total = clean(value(
                    row,
                    "total_line",
                    "total"
                ))

                home_implied = None
                away_implied = None

                if spread is not None and total is not None:
                    home_implied = (
                        float(total) - float(spread)
                    ) / 2

                    away_implied = (
                        float(total) + float(spread)
                    ) / 2

                cur.execute(
                    """
                    INSERT INTO games (
                        game_id,
                        season,
                        week,
                        game_date,
                        home_team_id,
                        away_team_id,
                        spread,
                        total,
                        home_implied_points,
                        away_implied_points,
                        home_score,
                        away_score,
                        status
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (game_id)
                    DO UPDATE SET
                        week = EXCLUDED.week,
                        game_date = EXCLUDED.game_date,
                        home_team_id = EXCLUDED.home_team_id,
                        away_team_id = EXCLUDED.away_team_id,
                        spread = EXCLUDED.spread,
                        total = EXCLUDED.total,
                        home_implied_points =
                            EXCLUDED.home_implied_points,
                        away_implied_points =
                            EXCLUDED.away_implied_points,
                        home_score = EXCLUDED.home_score,
                        away_score = EXCLUDED.away_score,
                        status = EXCLUDED.status,
                        updated_at = now()
                    """,
                    (
                        game_id,
                        clean(value(row, "season")),
                        clean(value(row, "week")),
                        game_datetime(
                            clean(value(row, "gameday")),
                            clean(value(row, "gametime")),
                        ),
                        home,
                        away,
                        spread,
                        total,
                        home_implied,
                        away_implied,
                        clean(value(row, "home_score")),
                        clean(value(row, "away_score")),
                        status,
                    ),
                )

            print("Games inserted.")

            # ==================================================
            # PLAYER WEEKLY STATS
            # ==================================================

            inserted = 0

            for row in stats.iter_rows(named=True):
                player_id = clean(value(row, "player_id"))
                game_id = clean(value(row, "game_id"))

                if not player_id or not game_id:
                    continue

                # Player should normally already exist.
                # This also protects us if nflverse contains
                # a player not present in load_players().
                player_name = clean(value(
                    row,
                    "player_display_name",
                    "player_name"
                ))

                cur.execute(
                    """
                    INSERT INTO players (
                        player_id,
                        player_name,
                        position
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT (player_id)
                    DO NOTHING
                    """,
                    (
                        player_id,
                        player_name or "Unknown",
                        clean(value(row, "position")),
                    ),
                )

                team = clean(value(row, "team"))

                if team:
                    cur.execute(
                        """
                        UPDATE players
                        SET team_id = %s,
                            updated_at = now()
                        WHERE player_id = %s
                        """,
                        (team, player_id),
                    )

                carries = clean(value(
                    row,
                    "carries",
                    "rushing_attempts"
                ))

                rushing_yards = clean(value(
                    row,
                    "rushing_yards",
                    "rush_yards"
                ))

                receptions = clean(value(
                    row,
                    "receptions"
                ))

                receiving_yards = clean(value(
                    row,
                    "receiving_yards",
                    "rec_yards"
                ))

                targets = clean(value(
                    row,
                    "targets"
                ))

                pass_attempts = clean(value(
                    row,
                    "attempts",
                    "pass_attempts"
                ))

                pass_yards = clean(value(
                    row,
                    "passing_yards",
                    "pass_yards"
                ))

                touchdowns = clean(value(
                    row,
                    "rushing_tds"
                ))

                receiving_tds = clean(value(
                    row,
                    "receiving_tds"
                ))

                passing_tds = clean(value(
                    row,
                    "passing_tds"
                ))

                td_total = 0

                for td in (
                    touchdowns,
                    receiving_tds,
                    passing_tds,
                ):
                    if td is not None:
                        td_total += int(td)

                cur.execute(
                    """
                    INSERT INTO player_game_stats (
                        player_id,
                        game_id,
                        targets,
                        carries,
                        receptions,
                        receiving_yards,
                        rush_yards,
                        pass_attempts,
                        pass_yards,
                        touchdowns,
                        air_yards,
                        yards_after_catch,
                        epa
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (player_id, game_id)
                    DO UPDATE SET
                        targets = EXCLUDED.targets,
                        carries = EXCLUDED.carries,
                        receptions = EXCLUDED.receptions,
                        receiving_yards =
                            EXCLUDED.receiving_yards,
                        rush_yards = EXCLUDED.rush_yards,
                        pass_attempts =
                            EXCLUDED.pass_attempts,
                        pass_yards = EXCLUDED.pass_yards,
                        touchdowns = EXCLUDED.touchdowns,
                        air_yards = EXCLUDED.air_yards,
                        yards_after_catch =
                            EXCLUDED.yards_after_catch,
                        epa = EXCLUDED.epa
                    """,
                    (
                        player_id,
                        game_id,
                        targets,
                        carries,
                        receptions,
                        receiving_yards,
                        rushing_yards,
                        pass_attempts,
                        pass_yards,
                        td_total,
                        clean(value(
                            row,
                            "receiving_air_yards",
                            "air_yards"
                        )),
                        clean(value(
                            row,
                            "receiving_yards_after_catch",
                            "yards_after_catch"
                        )),
                        clean(value(
                            row,
                            "receiving_epa",
                            "rushing_epa",
                            "passing_epa"
                        )),
                    ),
                )

                inserted += 1

            print(
                f"Player stat rows inserted/updated: {inserted}"
            )

        conn.commit()

    print("")
    print("============================================")
    print("SPORTS SNIPE NFL INGESTION COMPLETE")
    print("============================================")


if __name__ == "__main__":
    main()
