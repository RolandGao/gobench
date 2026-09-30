# GoBench
paper: https://rolandgao.com/gobench.pdf

Active leaderboard: https://rolandgao.com/blog/gobench/
<img width="1211" height="616" alt="Screenshot 2026-09-20 at 5 14 20 PM" src="https://github.com/user-attachments/assets/91745e05-56b6-4a1b-a3b0-a44cb6724cd9" />



## Setup

Use Python 3.12 or newer. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Run

Edit the `CONFIG = ArenaConfig(...)` block near the top of [arena.py](arena.py), then run:

```bash
python arena.py
```

## Summary

Generate a summary of the configured historical runs:

```bash
python arena.py --summary
```
The summary is here:
https://github.com/RolandGao/gobench/blob/main/log/summary/report.txt

### Automatic website updates

The [Update website](https://github.com/RolandGao/gobench/actions/workflows/update-website.yml) workflow triggers
a Cloudflare rebuild when `log/summary/results.json` or
`log/summary/report.txt` changes on `main`. Commit both summary files together
so the ratings and replay data describe the same results.

The website embeds charts and leaderboard summaries in its initial HTML at
build time, then refreshes data and loads game replays in the browser.

Setup: create a deploy hook for the `main` branch of the Cloudflare Worker
`rolandgao-github-io` and save its URL as this repository's Actions secret
`WEBSITE_DEPLOY_HOOK`. Keep the hook URL out of source control. Use the workflow's
**Run workflow** button to trigger a rebuild manually. A successful workflow
means Cloudflare accepted the request; check Cloudflare Builds for the final
deployment result.

If another GitHub Actions workflow pushes these files using `GITHUB_TOKEN`,
call the deploy hook from that workflow after the push as well: GitHub does
not start another push workflow for commits made with `GITHUB_TOKEN`.

## Citation
```
@misc{gao2026gobench,
  title = {{GoBench}: Evaluating {LLMs} on the Game of {Go}},
  author = {Gao, Roland},
  year = {2026},
  url = {https://rolandgao.com/gobench.pdf}
}
```

## License

[MIT License](LICENSE)
