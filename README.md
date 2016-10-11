### BitTorrent client

A BitTorrent client is written in Python and asyncio. Python 3.5+ is required.


### Setup

```bash
# Create a new virtual environment
pip install -r requirements.txt
python cli.py download ~/Downloads/tom.torrent   --loglevel=info --savedir=/tmp
```

### Serve Torrent file

``` bash
python cli.py upload ~/Downloads/tom.torrent --loglevel=debug
```

### Tests

```bash
pip install -r test_requirements.txt
pytest -s --cov=bt/ tests/
```

