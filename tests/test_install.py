"""install.sh copies the Pocket's modules one by one: every fm1-bt-bridge/*.py must be in its list, or a Pocket
fails with ModuleNotFoundError the first time that module is imported (as baudgirl.py and mvave.py did)

  python tests/test_install.py
"""

import re
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "fm1-bt-bridge"


def test_every_module_installed():
    script = (DIR / "install.sh").read_text()
    installed = set(re.findall(r'"\$DIR/(\w+\.py)"', script))
    missing = sorted(p.name for p in DIR.glob("*.py") if p.name not in installed)
    assert not missing, f"install.sh doesn't install: {', '.join(missing)}"


if __name__ == "__main__":
    test_every_module_installed()
    print("ok")
