import os
import plistlib
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "schedule_mac.sh"


def test_schedule_job_is_a_valid_daily_launchd_plist():
    env = dict(os.environ, DRY_RUN="1", PY="/x/.venv/bin/python", HOUR="7", MINUTE="5")
    out = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, check=True).stdout
    job = plistlib.loads(out)
    assert job["ProgramArguments"] == ["/x/.venv/bin/python", "-m", "cartcompass", "track"]
    assert job["StartCalendarInterval"] == {"Hour": 7, "Minute": 5}
    assert job["WorkingDirectory"] == str(SCRIPT.parent.parent)
