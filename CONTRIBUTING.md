# Contributing

Use Python 3.10+ on Linux. Create a virtual environment and install
`requirements.txt`, then run:

```bash
python -m unittest discover -v
QT_QPA_PLATFORM=offscreen python app.py --render /tmp/quota-preview.png
python release_source.py
```

The tests use a fake app-server and must not require account credentials or send
real account requests. Keep cancellation and timeout handling, reap subprocesses,
and display missing data as unknown. Preserve the 60-second quota/countdown update
interval unless the product behavior is intentionally changed.

Use XDG paths for runtime files and environment variables for executable overrides.
Never commit real quota output, personal screenshots, credentials, local launchers,
or a virtual environment. New public source files must also be added to the explicit
release manifest in `release_source.py`.

Contributions are accepted under the project's GPL-3.0-only license.
