# Contributing

Thanks for contributing to this EMG project.

## Quick Start

1. Fork the repository and create a feature branch.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run a quick sanity check:
   ```bash
   python main_pipeline.py --mode synthetic
   python main_pipeline.py --test synthetic
   ```
4. Open a pull request with a clear summary of changes.

## Contribution Guidelines

- Keep changes focused and minimal.
- Preserve existing command-line behavior unless intentionally changed.
- Update documentation when adding/changing functionality.
- Avoid committing generated files in `results/`.
- Use descriptive commit messages.

## Suggested Validation Before PR

- Pipeline still runs in synthetic mode.
- No import errors after fresh install.
- Any new arguments or presets are documented in `README.md`.
