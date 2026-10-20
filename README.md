# NFL Value Board

A website that grades every NFL player with 100+ snaps, projects what he’s worth on the market, and compares that to what he’s paid. It rebuilds itself every Tuesday after Monday Night Football.

- `docs/` is the website (GitHub Pages serves this folder).
- `docs/data/` holds the player data the site reads. The weekly job overwrites it.
- `build.py` pulls fresh data from nflverse, grades players and writes `docs/data/`.
- `.github/workflows/update.yml` runs `build.py` every Tuesday and commits the new data.

## Put it online (about 10 minutes, free)

1. **Create a repository.** On GitHub, click **New repository**, name it `nfl-value-board`, make it **Public**, and create it.
2. **Upload the files.** On the new repo’s page, choose **uploading an existing file**, then drag in everything from this folder: `build.py`, `requirements.txt`, `README.md`, `.gitignore`, and the `docs` folder. Commit.
3. **Add the weekly job.** Hidden folders like `.github` often don’t upload by drag-and-drop, so add it by hand: **Add file → Create new file**, type the name `.github/workflows/update.yml`, paste in the contents of that file from this folder, and commit.
4. **Turn on the website.** **Settings → Pages**. Under *Build and deployment*, set Source to **Deploy from a branch**, Branch to **main**, folder **/docs**, and save. After a minute your site is live at `https://YOUR-USERNAME.github.io/nfl-value-board/`.
5. **Test the update.** Go to the **Actions** tab, pick **Weekly data update**, and click **Run workflow**. When it finishes with a green check, the site has the newest week.

If the update fails at the “Commit updated data” step, go to **Settings → Actions → General → Workflow permissions**, choose **Read and write permissions**, save, and run it again.

## Run it on your own computer

```bash
pip install -r requirements.txt
python build.py                 # current season; SEASON=2025 python build.py for another
python -m http.server -d docs   # then open http://localhost:8000
```

## Changing the model

Everything lives near the top of `build.py`:

- `W`: which stats make up each position’s grade, and their weights.
- `AGE`: each position’s peak age and yearly decline.
- `STARTERS`: how many veteran contracts define each position’s market.
- `POOL_SNAPS`: snaps needed to be graded.

Data: [nflverse](https://github.com/nflverse/nflverse-data) (snap counts from Pro Football Reference, play-by-play stats, contracts from OverTheCap).
