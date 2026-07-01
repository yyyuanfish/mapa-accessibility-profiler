# Thesis Review Version

This repository is prepared as the review artifact for the thesis:

**MAPA: Accessibility Profiling and Personalized Journey Planning: A Multimodal Multi-Agent LLM-Based Framework**

## What the Review Version Contains

- backend source code for profiling, planning, providers, schemas, and evaluation
- frontend source code for the browser prototype
- generated evaluation files in `results/`
- API and implementation documentation in `docs/`
- pipeline overview in `pipeline_workflow.html`

## Version Freeze Rule

After thesis submission, the submitted code version should remain unchanged. The practical way to do this on GitHub is to create a tag and release for the submitted commit.

Recommended tag:

```bash
git tag -a thesis-submission-2026-07-01 -m "Thesis submission review version"
git push origin thesis-submission-2026-07-01
gh release create thesis-submission-2026-07-01 --title "Thesis submission review version" --notes "Fixed review version for the submitted thesis."
```

For later development, use a new branch, a new release tag, or a separate repository. The thesis should link to the repository or to the release page for the submitted version.

## GitHub Page Setup

Use the following repository settings on GitHub:

- Description: `Thesis prototype for consent-first accessibility profiling and personalized journey planning.`
- Website: `https://github.com/yyyuanfish/mapa-accessibility-profiler/releases/tag/thesis-submission-2026-07-01`
- Topics: `accessibility`, `journey-planning`, `multimodal`, `multi-agent-systems`, `computational-linguistics`, `zurich`
- Social preview image: upload `docs/assets/mapa-architecture.png`

To set the social preview image in the GitHub web interface, open the repository, go to `Settings`, then `General`, then `Social preview`, and upload the image.
