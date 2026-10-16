# ベースイメージと uv のイメージは、タグと digest で固定する（#21）。Dependabot（docker）が両方を更新する。
# Dependabot は FROM の行しか読まないので、uv も COPY --from=<イメージ> でなく、FROM の段にしてから使う。
# uv の版を上げたら、ci.yml の setup-uv の version も手で合わせる。
FROM ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 AS uv

FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS builder

COPY --from=uv /uv /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app
COPY pyproject.toml uv.lock ./
# ml（pyarrow・matplotlib。学習データの取得・EDA 用）は API のイメージに入れない。
# 予測に使う pandas・lightgbm・joblib は、プロジェクトの依存として入る。
RUN uv sync --locked --no-install-project --no-group ml


FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

# LightGBM が読み込む共有ライブラリ（OpenMP）。slim のイメージには入っていない。
# 版は固定しない（DL3008 をこの命令だけ除外）。Debian は古い版を消すので、固定するとビルドが壊れる。
# セキュリティの修正を受け取るため、そのときの最新を入れる。中身の脆弱性は #21 の Trivy で見る。
#
# 続けて、システムの pip を消す（#21）。API は pip を使わない（依存は builder の段で uv が入れる）。
# pip が中に抱えている部品（urllib3 など）に修正版のある脆弱性が見つかり、Trivy の検査で失敗したため。
# PATH の先頭は後で .venv の python になるので、システムの python を明示して呼ぶ。
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && /usr/local/bin/python -m pip uninstall --yes pip

RUN useradd --system --no-create-home --uid 10001 appuser

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY app ./app
COPY ml ./ml
# 学習済みモデル（/cloud-base が起動のときに読む）。root の所有のまま置き、appuser は読むだけ。
COPY models ./models

ENV PATH="/app/.venv/bin:$PATH"

# 上で作った appuser の uid。名前でなく数字で指定する（DL3066）。
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
