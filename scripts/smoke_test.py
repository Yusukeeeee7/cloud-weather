"""起動中の API のコンテナに問い合わせて、最低限の動作を確かめる（CD と手元の両方で使う）。

API のコンテナは `docker run --network none` で起動する。外部と通信できないので、
/cloud-base はモデルが読めていれば 502（upstream_error）、読めていなければ 503 になる。
ホストからは届かないため、同じイメージの別のコンテナをネットワークを共有させて起動し、
その中でこのスクリプトを実行する（標準ライブラリだけを使う。curl はイメージにない）：

    docker run --rm --network container:<API のコンテナ> -v <scripts>:/scripts:ro \
        <イメージ> python /scripts/smoke_test.py

1 つでも期待と違えば終了コード 1。
"""

import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
# 起動を待つ上限（秒）。
DEFAULT_WAIT_S = 60
# 1 回の問い合わせの上限（秒）。/cloud-base はリトライの待ち（0.5 秒 → 1.0 秒）の後に 502 になる。
DEFAULT_REQUEST_TIMEOUT_S = 30


@dataclass(frozen=True)
class Check:
    path: str
    status: int
    # 本文に含まれるべき文字列。
    text: str


CHECKS = (
    Check("/health", 200, '{"status":"ok"}'),
    Check("/daylight?city=tokyo", 200, '"city":"tokyo"'),
    Check("/cloud-base?city=tokyo", 502, '"code":"upstream_error"'),
)


def read_seconds(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    if not raw.isdigit() or not 1 <= int(raw) <= 9999:
        raise ValueError(f"{name} must be an integer from 1 to 9999")
    return int(raw)


def request(url: str, timeout_s: int) -> tuple[int, str]:
    """ステータスと本文を返す。つながらなければ 0 と空文字。"""
    try:
        # URL は既定の http://127.0.0.1:8000 か、実行する人が引数で渡したもの。
        # CD と手元で自分で実行するだけで、外部からの入力は受け取らない。
        with urllib.request.urlopen(url, timeout=timeout_s) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except OSError:
        # URLError（つながらない）とタイムアウトを含む。
        return 0, ""


def wait_until_ready(base_url: str, wait_s: int, timeout_s: int) -> bool:
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        status, _ = request(base_url + "/health", timeout_s)
        if status == 200:
            return True
        time.sleep(1)
    return False


def run_check(base_url: str, check: Check, timeout_s: int) -> bool:
    status, body = request(base_url + check.path, timeout_s)
    if status != check.status:
        print(f"NG: GET {check.path} returned {status} (expected {check.status})", file=sys.stderr)
        return False
    if check.text not in body:
        print(f"NG: GET {check.path} body does not contain {check.text}", file=sys.stderr)
        return False
    print(f"OK: GET {check.path} -> {status}")
    return True


def main(argv: list[str]) -> int:
    base_url = argv[1] if len(argv) > 1 else DEFAULT_BASE_URL
    try:
        wait_s = read_seconds("SMOKE_WAIT_S", DEFAULT_WAIT_S)
        timeout_s = read_seconds("SMOKE_REQUEST_TIMEOUT_S", DEFAULT_REQUEST_TIMEOUT_S)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    if not wait_until_ready(base_url, wait_s, timeout_s):
        print(f"NG: the API did not respond on /health within {wait_s}s", file=sys.stderr)
        return 1
    failures = sum(not run_check(base_url, check, timeout_s) for check in CHECKS)
    if failures:
        print(f"smoke test failed: {failures} check(s)", file=sys.stderr)
        return 1
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
