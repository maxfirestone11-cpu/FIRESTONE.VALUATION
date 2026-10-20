"""
Builds docs/data/players.json and docs/data/meta.json for the NFL Value Board.

Pulls the latest nflverse data (snap counts, weekly player stats, player IDs,
OverTheCap contracts), grades every player with enough snaps against others at
his position, projects a market value from grade + age, and records each
player's grade week by week so the site can show a trend.

Run:  python build.py            (current season)
      SEASON=2025 python build.py
"""
import io, json, os, sys, datetime as dt
import urllib.request
import numpy as np
import pandas as pd

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data")
CACHE = os.environ.get("NFL_CACHE")  # optional local folder of already-downloaded files
POOL_SNAPS = 100                      # full-season threshold to be graded
POOL_PER_WEEK = 20                    # early-season threshold = 20 snaps x weeks played


def fetch(path):
    name = path.split("/")[-1]
    if CACHE and os.path.exists(os.path.join(CACHE, name)):
        return open(os.path.join(CACHE, name), "rb").read()
    req = urllib.request.Request(f"{BASE}/{path}", headers={"User-Agent": "nfl-value-board"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def read_csv(path):
    return pd.read_csv(io.BytesIO(fetch(path)), low_memory=False)


def pick_season():
    if os.environ.get("SEASON"):
        return int(os.environ["SEASON"])
    today = dt.date.today()
    return today.year if today.month >= 9 else today.year - 1


# ---------------- position groups, weights, market, aging ----------------
GROUP = {"QB": "QB", "HB": "RB", "RB": "RB", "WR": "WR", "TE": "TE",
         "T": "OT", "OT": "OT", "G": "IOL", "C": "IOL", "OL": "IOL",
         "ED": "EDGE", "DE": "EDGE", "OLB": "EDGE", "DI": "IDL", "DT": "IDL", "NT": "IDL", "DL": "IDL",
         "LB": "LB", "MLB": "LB", "ILB": "LB", "CB": "CB", "S": "S", "SAF": "S", "FS": "S", "SS": "S", "DB": "CB"}

W = {
    "QB":  {"epa_per_dropback": .45, "passing_cpoe": .2, "td_int_rate": .15, "sack_rate": -.1, "qb_rush_epa": .1},
    "RB":  {"rush_epa_per_carry": .3, "ypc": .2, "scrim_yds_per_snap": .25, "first_downs_per_snap": .15, "fumbles_lost_total": -.1},
    "WR":  {"rec_yds_per_snap": .35, "epa_per_target": .25, "target_share": .2, "catch_rate": .1, "first_downs_per_snap": .1},
    "TE":  {"rec_yds_per_snap": .3, "epa_per_target": .25, "catch_rate": .15, "first_downs_per_snap": .1, "snap_share": .2},
    "OT":  {"team_sack_rate": -.35, "team_rush_epa": .3, "snap_share": .25, "penalties": -.1},
    "IOL": {"team_sack_rate": -.3, "team_rush_epa": .35, "snap_share": .25, "penalties": -.1},
    "EDGE": {"pass_rush_per_100": .55, "tfl_per_100": .2, "ballhawk_per_100": .1, "snap_share": .15},
    "IDL": {"pass_rush_per_100": .4, "tfl_per_100": .3, "tackles_per_100": .15, "snap_share": .15},
    "LB":  {"tackles_per_100": .3, "tfl_per_100": .2, "pass_rush_per_100": .15, "ballhawk_per_100": .2, "snap_share": .15},
    "CB":  {"ballhawk_per_100": .55, "tackles_per_100": .1, "snap_share": .25, "penalties": -.1},
    "S":   {"ballhawk_per_100": .45, "tackles_per_100": .2, "tfl_per_100": .1, "snap_share": .25},
}
OTC = {"QB": ["QB"], "RB": ["RB"], "WR": ["WR"], "TE": ["TE"], "OT": ["LT", "RT"], "IOL": ["LG", "RG", "C"],
       "EDGE": ["ED"], "IDL": ["IDL"], "LB": ["LB"], "CB": ["CB"], "S": ["S"]}
STARTERS = {"QB": 32, "RB": 32, "WR": 96, "TE": 40, "OT": 64, "IOL": 96, "EDGE": 64, "IDL": 64, "LB": 64, "CB": 80, "S": 64}
AGE = {"QB": (32, .07), "RB": (25, .11), "WR": (27, .08), "TE": (28, .08), "OT": (29, .07), "IOL": (29, .07),
       "EDGE": (28, .08), "IDL": (28, .08), "LB": (27, .09), "CB": (27, .10), "S": (28, .09)}

SUM_COLS = ["attempts", "completions", "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered",
            "passing_epa", "carries", "rushing_yards", "rushing_tds", "rushing_epa", "rushing_first_downs",
            "receptions", "targets", "receiving_yards", "receiving_tds", "receiving_epa", "receiving_first_downs",
            "receiving_yards_after_catch", "def_tackles_solo", "def_tackle_assists", "def_tackles_for_loss",
            "def_sacks", "def_qb_hits", "def_interceptions", "def_pass_defended", "def_fumbles_forced", "def_tds",
            "fantasy_points_ppr", "penalties", "fumbles_lost_total"]


def age_mult(g, age):
    if pd.isna(age):
        return 1.0
    peak, dec = AGE[g]
    if age < 24:
        return 1.05
    return max(0.35, 1 - dec * max(0, age - peak))


def grade_through(week, snaps, weekly, people):
    """Grade every qualifying player using games through `week`."""
    s = snaps[snaps.week <= week]
    agg = s.groupby("pfr_player_id").agg(
        player=("player", "last"), team=("team", "last"), snap_pos=("position", "last"),
        games=("game_id", "nunique"), off_snaps=("offense_snaps", "sum"), def_snaps=("defense_snaps", "sum"),
        off_pct=("offense_pct", "mean"), def_pct=("defense_pct", "mean")).reset_index()
    agg["snaps"] = agg.off_snaps + agg.def_snaps
    agg["snap_share"] = np.where(agg.off_snaps >= agg.def_snaps, agg.off_pct, agg.def_pct)

    df = agg.merge(people, left_on="pfr_player_id", right_on="pfr_id", how="left")

    def grp(r):
        for k in (r.pff_position, r.position, r.snap_pos):
            if isinstance(k, str) and k in GROUP:
                return GROUP[k]
        return None
    df["group"] = df.apply(grp, axis=1)
    df = df[df.group.notna() & (df.snaps >= min(POOL_SNAPS, POOL_PER_WEEK * week))].copy()

    w = weekly[weekly.week <= week].copy()
    st = w.groupby("player_id")[SUM_COLS].sum()
    cp = w[w.attempts > 0].assign(cw=lambda x: x.passing_cpoe.fillna(0) * x.attempts)
    cp = cp.groupby("player_id").agg(cw=("cw", "sum"), a=("attempts", "sum"))
    st["passing_cpoe"] = cp.cw / cp.a
    team_tgt = w.groupby("team").targets.sum()
    last_team = w.sort_values("week").groupby("player_id").team.last()
    st["target_share"] = st.targets / last_team.map(team_tgt).reindex(st.index)
    st = st.reset_index().rename(columns={"player_id": "gsis_id"})
    df = df.merge(st, on="gsis_id", how="left")
    num = SUM_COLS + ["passing_cpoe", "target_share"]
    df[num] = df[num].fillna(0)

    tq = w.groupby("team").agg(att=("attempts", "sum"), sk=("sacks_suffered", "sum"),
                               car=("carries", "sum"), repa=("rushing_epa", "sum"))
    tq["team_sack_rate"] = tq.sk / (tq.att + tq.sk)
    tq["team_rush_epa"] = tq.repa / tq.car
    df = df.merge(tq[["team_sack_rate", "team_rush_epa"]], left_on="team", right_index=True, how="left")

    o = df.off_snaps.clip(lower=1); d = df.def_snaps.clip(lower=1)
    db = (df.attempts + df.sacks_suffered).clip(lower=1)
    df["epa_per_dropback"] = df.passing_epa / db
    df["td_int_rate"] = (df.passing_tds - df.passing_interceptions) / db
    df["sack_rate"] = df.sacks_suffered / db
    df["qb_rush_epa"] = df.rushing_epa / o
    df["ypc"] = df.rushing_yards / df.carries.clip(lower=1)
    df["rush_epa_per_carry"] = df.rushing_epa / df.carries.clip(lower=1)
    df["scrim_yds_per_snap"] = (df.rushing_yards + df.receiving_yards) / o
    df["first_downs_per_snap"] = (df.rushing_first_downs + df.receiving_first_downs) / o
    df["rec_yds_per_snap"] = df.receiving_yards / o
    df["epa_per_target"] = df.receiving_epa / df.targets.clip(lower=1)
    df["catch_rate"] = df.receptions / df.targets.clip(lower=1)
    df["tackles"] = df.def_tackles_solo + df.def_tackle_assists
    df["pass_rush_per_100"] = 100 * (df.def_sacks + 0.5 * df.def_qb_hits) / d
    df["tfl_per_100"] = 100 * df.def_tackles_for_loss / d
    df["tackles_per_100"] = 100 * df.tackles / d
    df["ballhawk_per_100"] = 100 * (df.def_pass_defended + 2 * df.def_interceptions + 2 * df.def_fumbles_forced) / d
    df["total_epa"] = df.passing_epa + df.rushing_epa + df.receiving_epa

    df["score"] = np.nan
    for g, wts in W.items():
        m = df.group == g
        if m.sum() < 3:
            continue
        tot = 0
        for k, wt in wts.items():
            x = df.loc[m, k].astype(float)
            sd = x.std()
            z = (x - x.mean()) / (sd if sd and not np.isnan(sd) else 1)
            tot = tot + wt * z.clip(-3, 3)
        df.loc[m, "score"] = tot
    df = df[df.score.notna()].copy()
    df["pos_pct"] = df.groupby("group").score.rank(pct=True)
    df["grade"] = (50 + 45 * df.pos_pct).round(1)
    df["pos_rank"] = df.groupby("group").score.rank(ascending=False, method="min").astype(int)
    df["pos_count"] = df.groupby("group").score.transform("size")
    return df


def main():
    season = pick_season()
    try:
        snaps = read_csv(f"snap_counts/snap_counts_{season}.csv")
    except Exception:
        season -= 1
        snaps = read_csv(f"snap_counts/snap_counts_{season}.csv")
    snaps = snaps[snaps.game_type == "REG"]
    weekly = read_csv(f"stats_player/stats_player_week_{season}.csv")
    weekly = weekly[weekly.season_type == "REG"].copy()
    players = read_csv("players/players.csv")
    contracts = pd.read_parquet(io.BytesIO(fetch("contracts/historical_contracts.parquet")))

    last_week = int(min(snaps.week.max(), weekly.week.max()))
    asof = pd.Timestamp(dt.date.today())
    people = players[["pfr_id", "gsis_id", "pff_position", "position", "birth_date", "draft_round", "draft_pick",
                      "college_name", "headshot", "jersey_number", "years_of_experience"]].drop_duplicates("pfr_id")

    # grade trend: one grading pass per week (cumulative through that week)
    history = {}
    for wk in range(1, last_week + 1):
        g = grade_through(wk, snaps, weekly, people)
        for pid, gr in zip(g.pfr_player_id, g.grade):
            history.setdefault(pid, []).append([wk, float(gr)])

    df = grade_through(last_week, snaps, weekly, people)
    bd = pd.to_datetime(df.birth_date, errors="coerce")
    df["age"] = ((asof - bd).dt.days / 365.25).round(1)

    # contracts
    a = contracts[(contracts.is_active == True) & contracts.gsis_id.notna()]
    a = a.sort_values("year_signed").drop_duplicates("gsis_id", keep="last")
    df = df.merge(a[["gsis_id", "apy", "value", "guaranteed", "years", "year_signed", "apy_cap_pct", "draft_year"]]
                  .rename(columns={"value": "contract_total", "years": "contract_years"}), on="gsis_id", how="left")
    df["rookie_deal"] = df.year_signed == df.draft_year

    vet = contracts[(contracts.is_active == True) & (contracts.year_signed != contracts.draft_year)]
    market = {g: np.sort(np.sort(vet[vet.position.isin(ps)].apy.values)[::-1][:STARTERS[g]]) for g, ps in OTC.items()}
    df["age_mult"] = [age_mult(g, x) for g, x in zip(df.group, df.age)]
    df["market_apy"] = [float(np.quantile(market[g], pc ** 1.2)) for g, pc in zip(df.group, df.pos_pct)]
    df["projected_apy"] = (df.market_apy * df.age_mult).round(2)
    df["surplus"] = (df.projected_apy - df.apy).round(2)
    df["cost_per_snap"] = (df.apy * 1e6 / (df.snaps / last_week * 17)).round(0)

    def r(x, n=3):
        return x.astype(float).round(n)

    out = pd.DataFrame({
        "id": df.pfr_player_id, "player": df.player, "pos": df.group, "team": df.team, "age": df.age,
        "jersey": df.jersey_number, "headshot": df.headshot, "college": df.college_name,
        "draft_round": df.draft_round, "draft_pick": df.draft_pick, "exp": df.years_of_experience,
        "games": df.games, "snaps": df.snaps.astype(int), "snap_share": r(df.snap_share),
        "grade": df.grade, "pos_rank": df.pos_rank, "pos_count": df.pos_count,
        "apy": df.apy.round(2), "worth": df.projected_apy, "surplus": df.surplus,
        "guaranteed": df.guaranteed.round(1), "contract_years": df.contract_years, "year_signed": df.year_signed,
        "cap_pct": r(df.apy_cap_pct), "rookie_deal": df.rookie_deal, "cost_per_snap": df.cost_per_snap,
        "total_epa": r(df.total_epa, 1), "ppr": r(df.fantasy_points_ppr, 1),
        "cmp": df.completions.astype(int), "att": df.attempts.astype(int),
        "pass_yds": df.passing_yards.astype(int), "pass_td": df.passing_tds.astype(int), "int": df.passing_interceptions.astype(int),
        "epa_db": r(df.epa_per_dropback), "cpoe": r(df.passing_cpoe, 1), "sacked": df.sacks_suffered.astype(int),
        "carries": df.carries.astype(int), "rush_yds": df.rushing_yards.astype(int), "ypc": r(df.ypc, 2), "rush_td": df.rushing_tds.astype(int),
        "targets": df.targets.astype(int), "rec": df.receptions.astype(int), "rec_yds": df.receiving_yards.astype(int),
        "rec_td": df.receiving_tds.astype(int), "tgt_share": r(df.target_share), "yac": df.receiving_yards_after_catch.astype(int),
        "epa_tgt": r(df.epa_per_target),
        "tackles": df.tackles.astype(int), "tfl": df.def_tackles_for_loss.astype(int), "sacks": r(df.def_sacks, 1),
        "qb_hits": df.def_qb_hits.astype(int), "pd": df.def_pass_defended.astype(int), "def_int": df.def_interceptions.astype(int),
        "ff": df.def_fumbles_forced.astype(int), "penalties": df.penalties.astype(int),
        "team_sack_rate": r(df.team_sack_rate), "team_rush_epa": r(df.team_rush_epa),
    })
    out["hist"] = out.id.map(lambda i: history.get(i, []))
    out = out.sort_values("grade", ascending=False)
    out = out.astype(object).where(out.notna(), None)

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "players.json"), "w") as f:
        json.dump(out.to_dict("records"), f, separators=(",", ":"))
    meta = {"season": season, "week": last_week, "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "players": len(out), "pool_snaps": POOL_SNAPS}
    with open(os.path.join(OUT, "meta.json"), "w") as f:
        json.dump(meta, f)
    print(f"Built {len(out)} players, {season} season through week {last_week}")


if __name__ == "__main__":
    sys.exit(main())
